"""
This lambda function creates an account (customer/vendor) in Zoho Books
and logs the response in a DynamoDB table.
"""

import requests
import boto3
import json
from datetime import datetime
from src.email import send_failure_email

dynamodb = boto3.resource('dynamodb')
eventbridge = boto3.client('events')

# Function to send event to Salesforce via EventBridge
def salesforce_eventbridge(event, sf_account_id, zoho_customer_id, zoho_vendor_id):
    try:
        salesforce_payload = {
            "Status__c" : "ZohoAccountCreated",
            "recordId__c": sf_account_id,
            "External_ID__c": zoho_customer_id,
            "Zoho_Vendor_Id__c": zoho_vendor_id
        }
        # Send event to Salesforce via EventBridge
        response_sf = eventbridge.put_events(
            Entries=[
                {
                    "Source": "zoho-account",
                    "DetailType": "zoho-account",
                    "Detail": json.dumps(salesforce_payload),
                    "EventBusName": event.get("event_bus_name")
                }
            ]
        )
        return "Success"
    except Exception as e:
        return str(e)

def create_account_function(event):
    # Extract required fields from the event
    print("test")
    client_id = event.get("client_id")
    client_secret = event.get("client_secret")
    refresh_token = event.get("refresh_token")
    org_id = event.get("org_id")
    account_table =  event.get("account_table")
    sf_account_id = event.get("RecordID__c")
    table = dynamodb.Table(account_table)

    gst_type_mapping = {
        "Regular": "business_gst",
        "SEZ": "business_sez",
        "Overseas": "overseas"
    }
    
    # Validate required fields
    if not all([client_id, client_secret, refresh_token, org_id]):
        return {"error": "Missing required fields: client_id, client_secret, refresh_token, org_id"}
    
    # Prepare DynamoDB payload
    dynamodb_account_payload = {
        "Company_Name": event.get("TradeName__c"),
        "Account_Type": event.get("AccountType__c"),
    }

    res = table.get_item(Key={'Account_ID': event.get("RecordID__c")})
    if 'Item' in res:
        item = res['Item']
        if event.get("AccountType__c") == "Buyer" and item.get("Zoho_Customer_ID"):
            resp1 = salesforce_eventbridge(event, sf_account_id, item.get("Zoho_Customer_ID"), None)
            return {"error": "The Customer is created for this Buyer in Zoho Books already. And it's id is " + str(item.get("Zoho_Customer_ID")) +". For more details please check DynamoDB. Again posted of Salesforce and response is " + str(resp1)}
        elif event.get("AccountType__c") == "Seller" and item.get("Zoho_Vendor_ID") and item.get("Zoho_Customer_ID"):
            resp1 = salesforce_eventbridge(event, sf_account_id, item.get("Zoho_Customer_ID"), item.get("Zoho_Vendor_ID"))
            return {"error": "Both Customer and Vendor are created for this Vendor in Zoho Books already. And it's vendor id is " + str(item.get("Zoho_Vendor_ID")) +"and customer id is "+ str(item.get("Zoho_Customer_ID")) +". For more details please check DynamoDB. Again posted of Salesforce and response is " + str(resp1)}
        else:
            print("Record exists but missing Zoho IDs, proceeding to create missing account types.")
    # if 'Item' in table.get_item(Key={'Account_ID': event.get("RecordID__c")}):
    #     return {"error": "Account already exists in DynamoDB"}

    
    # Generate access token
    generate_access_token_url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://www.zoho.in/books",
        "grant_type": "refresh_token"
    }
    token_response = requests.post(generate_access_token_url, data=data)
    print("Zoho token response:", token_response.text)
    # Check if token generation was successful
    if token_response.status_code != 200:
        send_failure_email("Zoho Token Generation Failed", "Failed to generate access token for Zoho Books API.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Failed to generate access token"}
    # Extract access token from the response
    access_token = token_response.json().get("access_token")
    # Check if access token is present
    if not access_token:
        send_failure_email("Zoho Token Generation Failed", "Failed to generate access token for Zoho Books API.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Access token not found in response"}
    
    # Create account in Zoho Books
    create_account_url = f"https://www.zohoapis.in/books/v3/contacts?organization_id={org_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }
    # Prepare payload for account creation
    payload = {
        "contact_name": event.get("TradeName__c"),
        "company_name": event.get("TradeName__c"),
        "billing_address": {
            "address": event.get("BillingStreet__c"),
            "city": event.get("BillingCity__c"),
            "state": event.get("BillingState__c"),
            "zip": event.get("BillingPostalCode__c"),
            "country": event.get("BillingCountry__c")
        },
        "shipping_address": {
            "address": event.get("ShippingStreet__c"),
            "city": event.get("ShippingCity__c"),
            "state": event.get("ShippingState__c"),
            "zip": event.get("ShippingPostalCode__c"),
            "country": event.get("ShippingCountry__c")
        }
    }

    # Add GST details if provided
    if event.get("prod_flag") == "1":
        payload["gst_treatment"] = gst_type_mapping.get(event.get("GSTTreatement__c"))
        # Add gst_number only if GST_Type is not Overseas
        if event.get("GSTTreatement__c") != "Overseas":
            payload["gst_no"] = event.get("GSTIN__c")
        elif event.get("GSTTreatement__c") == "Overseas" and event.get("PAN__c"):
            payload["pan_no"] = event.get("PAN__c")
        else: 
            print("PAN Number not provided for Overseas GST Type")

    # Create account(s) based on the creation_type    
    if event.get("AccountType__c") == "Seller":
        # Create Customer
        payload["contact_type"] = "customer"
        response_1 = requests.post(create_account_url, headers=headers, json=payload)
        # Log API response with timestamp
        api_response_1 = {
            "Customer_API": response_1.status_code,
            "Customer_API_timestamp": str(datetime.now())
        }
        # Check if customer account creation was successful
        if response_1.status_code == 201:
            resp_1 = response_1.json().get("contact", {}).get("contact_id")
        else:
            send_failure_email("Zoho Customer Account Creation Failed", "Failed to create customer account of the seller: "+ event.get("TradeName__c") + response_1.text, event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
            return {"error": "Failed to create customer account of the seller: " + response_1.text}

        # Log customer ID and API response in DynamoDB payload
        dynamodb_account_payload["Zoho_Customer_ID"] = resp_1
        dynamodb_account_payload["Customer_API_Response"] = api_response_1

        # Create Vendor
        payload["contact_type"] = "vendor"
        if event.get("MSMENumber__c") and event.get("MSMEType__c"):
            payload["udyam_reg_no"] = event.get("MSMENumber__c")
            payload["msme_type"] = event.get("MSMEType__c").lower()
        response_2 = requests.post(create_account_url, headers=headers, json=payload)
        # Log API response with timestamp
        api_response_2 = {
            "Vendor_API": response_2.status_code,
            "Vendor_API_timestamp": str(datetime.now())
        }
        # Check if vendor account creation was successful
        if response_2.status_code == 201:
            resp_2 = response_2.json().get("contact", {}).get("contact_id")
        else:
            resp_2 = None
            send_failure_email("Zoho Vendor Account Creation Failed", "Failed to create vendor account of the seller: "+ event.get("TradeName__c") + "Customer Account of the created, but vendor account failed. " + "\n" + response_2.text, event.get("failure_mail_sender"), event.get("failure_mail_reciever"))

        # Log vendor ID and API response in DynamoDB payload
        dynamodb_account_payload["Zoho_Vendor_ID"] = resp_2
        dynamodb_account_payload["Vendor_API_Response"] = api_response_2

        # Log API responses in CloudWatch payload
        cloudwatch_payload = {
            "Customer API Response": response_1.json(),
            "Vendor API Response": response_2.json()
        }

    elif event.get("AccountType__c") == "Buyer":
        # Create Customer
        payload["contact_type"] = "customer"
        response_1 = requests.post(create_account_url, headers=headers, json=payload)
        # Log API response with timestamp
        api_response = {
            "Customer_API": response_1.status_code,
            "Customer_API_timestamp": str(datetime.now())
        }
        # Check if customer account creation was successful
        if response_1.status_code == 201:
            resp_1 = response_1.json().get("contact", {}).get("contact_id")
        else:
            resp_1 = None
            send_failure_email("Zoho Customer Account Creation Failed", "Failed to create customer account of the buyer: "+ event.get("TradeName__c") + "\n" + response_1.text, event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        
        # Log customer ID and API response in DynamoDB payload
        dynamodb_account_payload["Zoho_Customer_ID"] = resp_1
        dynamodb_account_payload["Zoho_Vendor_ID"] = ""
        dynamodb_account_payload["Customer_API_Response"] = api_response

        # Log API responses in CloudWatch payload
        cloudwatch_payload = {
            "Customer API Response": response_1.json()
        }


# Use the below code to create only vendor accounts if needed in future
    # elif event.get("AccountType__c")== "Vendor":
    #     # Create Vendor
    #     payload["contact_type"] = "vendor"
    #     response_1 = requests.post(create_account_url, headers=headers, json=payload)
    #     # Log API response with timestamp
    #     api_response = {
    #         "Vendor_API": response_1.status_code,
    #         "Vendor_API_timestamp": str(datetime.now())
    #     }
    #     # Check if vendor account creation was successful
    #     if response_1.status_code == 201:
    #         resp_1 = response_1.json().get("contact", {}).get("contact_id")
    #     else:
    #         resp_1 = None
        
    #     # Log vendor ID and API response in DynamoDB payload
    #     dynamodb_account_payload["Zoho_Vendor_ID"] = resp_1
    #     dynamodb_account_payload["Zoho_Customer_ID"] = ""
    #     dynamodb_account_payload["Vendor_API_Response"] = api_response
        
    #     # Log API responses in CloudWatch payload
    #     cloudwatch_payload = {
    #         "Vendor API Response": response_1.json(),
    #     }

    # Invalid account type
    else:
        return {"error": "Invalid account type, please choose from Customer, Vendor, Customer and Vendor."}
    

    # Send event to Salesforce via EventBridge
    resp2 = salesforce_eventbridge(event, sf_account_id, dynamodb_account_payload.get("Zoho_Customer_ID"), dynamodb_account_payload.get("Zoho_Vendor_ID"))
    if resp2 == "Success":
        cloudwatch_payload["Salesforce_EventBridge_Response"] = "Success"
        dynamodb_account_payload["Salesforce"] = "Published"
    else:
        send_failure_email("Salesforce EventBridge Failed", "Failed to send event to Salesforce via EventBridge. Error: "+ str(resp2), event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        cloudwatch_payload["Salesforce_EventBridge_Response"] = resp2
        dynamodb_account_payload["Salesforce"] = "Failed"
        
    # Insert record into DynamoDB
    try:
        dynamodb_account_payload["Created_At"] = str(datetime.now())
        update_fields = {k: v for k, v in dynamodb_account_payload.items() if k not in ["Account_ID"]}
        expression_attribute_names = {f"#{k.replace(' ', '_')}": k for k in update_fields.keys()}
        expression_attribute_values = {f":{k.replace(' ', '_')}": v for k, v in update_fields.items()}
            # Build the UpdateExpression dynamically
        update_expr = "SET " + ", ".join(f"#{k.replace(' ', '_')} = :{k.replace(' ', '_')}" for k in update_fields.keys())

        table.update_item(
            Key={
                "Account_ID": sf_account_id   
            },
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )
        # Log DynamoDB insertion success in CloudWatch payload
        cloudwatch_payload["DynamoDB_Insert"] = "Success"
        return cloudwatch_payload

    except Exception as e:
        cloudwatch_payload["DynamoDB_Insert"] = "Failed"
        cloudwatch_payload["DynamoDB Error"] = str(e)
        send_failure_email("DynamoDB Insertion Failed", "Failed to insert account record into DynamoDB. Error: "+ str(e), event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return cloudwatch_payload