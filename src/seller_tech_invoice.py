import requests
from src.get_invoice import get_invoice_function
import boto3
import json
from datetime import datetime
from src.email import send_failure_email

dynamodb = boto3.resource('dynamodb')
eventbridge = boto3.client('events')

tax_map = {
    "18.00" : "1743550000000023299",
    "5.00" : "1743550000000023295",
    "0.00" : "1743550000000023293",
    "40.00" : "1743550000000901046"
}

def tax_id(val):
    formatted = f"{val:.2f}"
    tax_id_map = tax_map[formatted]
    return tax_id_map

# Seller Technology Fee invoice creation function
def seller_tech_invoice_function(event):
    client_id = event.get("client_id")
    client_secret = event.get("client_secret")
    refresh_token = event.get("refresh_token")
    org_id = event.get("org_id")
    invoice_table = event.get("invoice_table")
    table = dynamodb.Table(invoice_table)

    cloudwatch_payload = {}

    # Validate required fields
    if not all([client_id, client_secret, refresh_token, org_id]):
        return {"error": "Missing required fields: client_id, client_secret, refresh_token, org_id"}

    inside_payload = json.loads(event.get("Payload__c"))
    invoice_number = event.get("InvoiceNumber__c")

    # Check for Overseas GST Treatment
    if event.get("overseas_flag") == "0" and inside_payload.get("account").get("GSTTreatment") == "Overseas":
        send_failure_email("Invalid GST Treatment for Seller Tech Invoice", f"Cannot create invoice for Overseas GST Treatment when overseas_flag is 0 for Invoice_Number {invoice_number}.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Cannot create invoice for Overseas GST Treatment when overseas_flag is 0"}

    # Prepare DynamoDB payload
    dynamodb_payload = {
        "Invoice_Number": event.get("InvoiceNumber__c"),
        "Customer_ID": inside_payload.get("account").get("zohoAccountId"),
    }

    # Check for duplicate invoice
    if 'Item' in table.get_item(Key={'Invoice_Number': event.get("InvoiceNumber__c")}):
        send_failure_email("Duplicate Invoice Creation Attempt", f"Invoice with Invoice_Number {invoice_number} already exists in Zoho for seller tech, and Salesforce is sending playload with null Zoho invoice ID.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Invoice with this Invoice_Number already exists in Zoho, and Salesforce is sending playload with null Zoho invoice ID."}
    
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
    # print("Zoho token response:", token_response.text)

    # Handle token generation failure
    if token_response.status_code != 200:
        send_failure_email("Zoho Token Generation Failed", "Failed to generate access token for Zoho Books API.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Failed to generate access token"}
    access_token = token_response.json().get("access_token")


    #     Set up invoice creation payload
    create_invoice_url = f"https://www.zohoapis.in/books/v3/invoices?organization_id={org_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }

    # Prepare invoice payload
    payload = {
        "invoice_number" : event.get("InvoiceNumber__c"),
        "customer_id": inside_payload.get("account").get("zohoAccountId"),
        "template_id": event.get("seller_tech_invoice_template_id"),
        "terms": event.get("seller_tech_terms"),
        "notes": event.get("seller_tech_notes")
    }

    #  Set line item details
    zoho_line_items = [{}] * 1
    zoho_item = {
        "rate": inside_payload.get("invoice").get("techFeeAmount"),
        "quantity": 1,
        "name": event.get("Product_Details__c")
    }

    # Set line item details based on product flag
    if event.get("prod_flag") == "1":
        if event.get("TechFeeHSN"):
            zoho_item["hsn_or_sac"] = event.get("seller_tech_hsn")
        if event.get("TechFeeGST"):
            zoho_item["tax_id"] = tax_id(float(event.get("seller_tech_gst", 18.0)))
    zoho_line_items[0] = zoho_item
    
    payload["line_items"] = zoho_line_items

    response = requests.post(create_invoice_url, headers=headers, json=payload)
    # print("Zoho create invoice response:", response.text)
    # print("Response status code:", response.status_code)

    # Handle invoice creation response
    create_invoice_response = {
            "API_Status": response.status_code,
            "API_Timestamp" : str(datetime.now())
        }
    
    # dynamodb_payload["CREATE_Invoice_Response"] = create_invoice_response
    if response.status_code == 201:
        resp_json = response.json()
        invoice_id = resp_json.get("invoice", {}).get("invoice_id")
        
        dynamodb_payload["Zoho_Invoice_ID"] = invoice_id
        # After creating invoice, call get_invoice_function to fetch PDF (and handle copies/upload)
        # determine copies safely: account may be missing or have invoiceCopies=None
        account_obj = inside_payload.get("account") or {}
        copies_value = account_obj.get("invoiceCopies")
        if copies_value is None:
            copies_value = 1

        # Prepare event for get_invoice_function
        get_event = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "org_id": org_id,
            "invoice_number": event.get("InvoiceNumber__c"),
            "sf_invoice_id": inside_payload["invoice"]["invoiceId"],
            "invoice_id": invoice_id,
            "bucket_name": event.get("bucket_name"),
            "invoice_url_prefix": event.get("invoice_url_prefix"),
            "copies": copies_value,
            "annexure_data": inside_payload.get("shipments", []),
        }
        # print(f"Calling get_invoice_function for invoice_id: {invoice_id}")
        get_result = get_invoice_function(get_event)
        body, status_code = get_result

        get_invoice_response = {
            "API_Status": status_code,
            "API_Timestamp" : str(datetime.now())
        }

        # Handle get_invoice_function response 
        if status_code == 200:
            invoice_url = body.get("s3_location")
        else:
            send_failure_email("Get TInvoice Function Failed", "Either Failed to get seller tech invoice of Id " + event.get("InvoiceNumber__c") + " or failed to store in S3. No Invoice URL on Salesforce. Error: "+ str(body.get("error")), event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
            invoice_url = None
            cloudwatch_payload["Get_Invoice_Error"] = body.get("error")
            get_invoice_response["Error_Details"] = body.get("error")
        
        # dynamodb_payload["GET_Invoice_Response"] = get_invoice_response
        final_api_response = {
            "CREATE_Invoice_Response": create_invoice_response,
            "GET_Invoice_Response": get_invoice_response
        }
        dynamodb_payload["Create_Invoice"] = final_api_response
        
        dynamodb_payload["Invoice_URL"] = invoice_url
        # dynamodb_payload["API_Response"] = body

    else:
        dynamodb_payload["Zoho_Invoice_ID"] = None
        dynamodb_payload["Invoice_URL"] = None
        send_failure_email("Zoho Invoice Creation Failed", "Failed to create seller tech invoice for Id " + event.get("InvoiceNumber__c") + "in Zoho Books: "+ response.text, event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Failed to create invoice", "details": response.json()}
    
    # Salesforce payload via EventBridge
    try:
        salesforce_payload = {
            "Status__c" : "Zoho_Invoice_Created",
            "ZohoInvoiceId__c": dynamodb_payload["Zoho_Invoice_ID"],
            "InvoiceURL__c": dynamodb_payload["Invoice_URL"],
            "SFInvoiceRecordId__c" : inside_payload["invoice"]["invoiceId"]
        }
        eventbridge.put_events(
            Entries=[
                {
                    "Source": "zoho-invoice",
                    "DetailType": "zoho-invoice",
                    "Detail": json.dumps(salesforce_payload),
                    "EventBusName": event.get("event_bus_name")
                }
            ]
        )
        dynamodb_payload["Salesforce"] = "Published"
    except Exception as e:
        send_failure_email("AWS Salesforce EventBridge Failed", f"Failed to send event to Salesforce via EventBridge for seller techinvoice: {event.get('InvoiceNumber__c')}. Error: {str(e)}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        print(f"Warning: Failed to create Salesforce payload: {str(e)}")
        cloudwatch_payload["Salesforce_EventBridge_Error"] = str(e)
        dynamodb_payload["Salesforce"] = "Failed"
    
    # Store invoice details in DynamoDB
    try:
        table.put_item(Item=dynamodb_payload)
        cloudwatch_payload["DynamoDB_Insertion"] = "Success"
        return cloudwatch_payload
    except Exception as e:
        send_failure_email("DynamoDB Insertion Failed", f"Failed to store seller tech invoice: {event.get('InvoiceNumber__c')} details in DynamoDB. Error: {str(e)}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        cloudwatch_payload["DynamoDB_Insertion_Error"] = str(e)
        return cloudwatch_payload