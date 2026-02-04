"""
Create invoice in Zoho Books and handle related operations.
This module defines the `create_invoice_function` which creates an invoice in Zoho Books
using provided credentials and payload. It also handles fetching the invoice PDF,
managing copies, uploading to S3, and updating Salesforce via EventBridge.
"""


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

# Function to create invoice in Zoho Books
def create_invoice_function(event):
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

    # Parse the payload from the event
    inside_payload = json.loads(event.get("Payload__c"))
    invoice_number = event.get("InvoiceNumber__c")

    # Check GST Treatment and overseas_flag
    if event.get("overseas_flag") == "0" and inside_payload.get("account").get("GSTTreatment") == "Overseas":
        send_failure_email("Invalid GST Treatment for Seller Tech Invoice", f"Cannot create invoice for Overseas GST Treatment when overseas_flag is 0 for Invoice_Number {invoice_number}.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Cannot create invoice for Overseas GST Treatment when overseas_flag is 0"}

    # Prepare DynamoDB payload
    dynamodb_payload = {
        "Invoice_Number": event.get("InvoiceNumber__c"),
        "Customer_ID": inside_payload.get("account").get("zohoAccountID"),
    }

    # Check for duplicate invoice
    if 'Item' in table.get_item(Key={'Invoice_Number': event.get("InvoiceNumber__c")}):
        send_failure_email("Duplicate Invoice Creation Attempt", f"Invoice with Invoice_Number {invoice_number} already exists in Zoho, and Salesforce is sending playload with null Zoho invoice ID.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Invoice with this Invoice_Number already exists in Zoho, and Salesforce is sending playload with null Zoho invoice ID."}
    
    # Generate access token for Zoho Books API
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
    # Check if token generation was successful
    if token_response.status_code != 200:
        send_failure_email("Zoho Token Generation Failed", "Failed to generate access token for Zoho Books API.", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Failed to generate access token"}
    access_token = token_response.json().get("access_token")

    # Create invoice in Zoho Books
    create_invoice_url = f"https://www.zohoapis.in/books/v3/invoices?organization_id={org_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }

    # Prepare payload for invoice creation
    payload = {
        "invoice_number" : event.get("InvoiceNumber__c"),
        "customer_id": inside_payload.get("account").get("zohoAccountID"),
        "reference_number" : event.get("PONumber__c")
    }
    
    # Prepare line items for invoice creation
    sf_line_items = inside_payload.get("lineItems", [])
    zoho_line_items = []
    for i in range(len(sf_line_items)):
        sf_item = sf_line_items[i]
        zoho_item = {
            "rate": sf_item.get("unitPrice"),
            "quantity": int(sf_item.get("quantity")),
            "name": sf_item.get("product")
        }

        # Add description, HSN/SAC, and tax percentage if available
        ref = sf_item.get("RefCode")
        uom = sf_item.get("UoM")
        if ref and uom:
            zoho_item["description"] = f"{uom} | {ref}"
        else:
            zoho_item["description"] = uom
        if event.get("prod_flag") == "1" and sf_item.get("hsn"):
            zoho_item["hsn_or_sac"] = sf_item.get("hsn")
        if event.get("prod_flag") == "1" and sf_item.get("gst"):
            
            if inside_payload.get("account", {"GSTTreatment": "Regular"}).get("GSTTreatment", "Regular") == "Regular":
                zoho_item["tax_id"] = tax_id(float(sf_item.get("gst", 0.0)))
            else:
                zoho_item["tax_id"] = tax_id(0.00)

        zoho_line_items.append(zoho_item)
    
    payload["line_items"] = zoho_line_items

    # Add shipping charge if available
    if inside_payload.get("shipment").get("shippingCost"):
        payload["shipping_charge"] = inside_payload.get("shipment").get("shippingCost")

    # GST MAPPING
    gst_type_mapping = {
        "Regular": "business_gst",
        "SEZ": "business_sez",
        "Overseas": "overseas"
    }
    
    # Add additional fields  based on prod_flag
    if event.get("prod_flag") == "1":
        # if event.get("prod_flag") == "1" and sf_item.get("gst"):
        payload["gst_treatment"] = gst_type_mapping[inside_payload.get("account", {"GSTTreatment": "Regular"}).get("GSTTreatment", "Regular")]

        if inside_payload.get("shipment").get("shippingCost"):
            payload["shipping_charge_sac_code"] = event.get("shipping_sac", "996511")
            if inside_payload.get("account", {"GSTTreatment": "Regular"}).get("GSTTreatment", "Regular") == "Regular":
                payload["shipping_charge_tax_id"] = tax_id(float(event.get("shipping_gst", 18.0)))
            else:
                payload["shipping_charge_tax_id"] = tax_id(0.00)
            # payload["shipping_charge_tax_id"] = tax_id(str(event.get("shipping_gst", "18")))
        custom_fields = []
        if event.get("LUTNumber__c"):
            lut_no = {
                "api_name": "cf_lut_no",
                "value": event.get("LUTNumber__c")
            }
            custom_fields.append(lut_no)

        if inside_payload.get("order").get("PoDate"):
            po_date = {
                "api_name": "cf_po_date",
                "value": inside_payload.get("order").get("PoDate")
            }
            custom_fields.append(po_date)

        if inside_payload.get("order").get("orderNumber"):
            order_number = {
                "api_name": "cf_order_no",
                "value": inside_payload.get("order").get("orderNumber")
            }
            custom_fields.append(order_number)

        if inside_payload.get("shipment").get("Shipmentname"):
            shipment_number = {
                "api_name": "cf_shipment_no",
                "value": inside_payload.get("shipment").get("Shipmentname")
            }
            custom_fields.append(shipment_number)

        payload["custom_fields"] = custom_fields


    # Create invoice in Zoho Books
    cloudwatch_payload["zoho_payload"] = payload
    response = requests.post(create_invoice_url, headers=headers, json=payload)

    # Prepare create invoice response for DynamoDB
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
            "sf_invoice_id": inside_payload["invoice"]["Invoiceid"],
            "invoice_id": invoice_id,
            "bucket_name": event.get("bucket_name"),
            "invoice_url_prefix": event.get("invoice_url_prefix"),
            "copies": copies_value,
            "annexure_data": event.get("annexure_data")
        }
        # print(f"Calling get_invoice_function for invoice_id: {sf_invoice_id}")
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
            send_failure_email("Get Invoice Function Failed", "Either Failed to get invoice of Id " + event.get("InvoiceNumber__c") + " or failed to store in S3. No Invoice URL on Salesforce. Error: "+ str(body.get("error")), event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
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
        send_failure_email("Zoho Invoice Creation Failed", "Failed to create invoice for Id " + event.get("InvoiceNumber__c") + "in Zoho Books: "+ response.text, event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        return {"error": "Failed to create invoice", "details": response.json()}
    
    # Salesforce
    try:
        # Prepare Salesforce payload and send event via EventBridge
        salesforce_payload = {
            "Status__c" : "Zoho_Invoice_Created",
            "ZohoInvoiceId__c": dynamodb_payload["Zoho_Invoice_ID"],
            "InvoiceURL__c": dynamodb_payload["Invoice_URL"],
            "SFInvoiceRecordId__c" : inside_payload["invoice"]["Invoiceid"]
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
    
    # Handle exceptions during Salesforce EventBridge publishing
    except Exception as e:
        send_failure_email("AWS Salesforce EventBridge Failed", f"Failed to send event to Salesforce via EventBridge for buyer invoice: {event.get('InvoiceNumber__c')}. Error: {str(e)}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        print(f"Warning: Failed to create Salesforce payload: {str(e)}")
        cloudwatch_payload["Salesforce_EventBridge_Error"] = str(e)
        dynamodb_payload["Salesforce"] = "Failed"
    
    # Store invoice details in DynamoDB
    try:
        table.put_item(Item=dynamodb_payload)
        cloudwatch_payload["DynamoDB_Insertion"] = "Success"
        return cloudwatch_payload
    # Handle exceptions during DynamoDB insertion
    except Exception as e:
        send_failure_email("DynamoDB Insertion Failed", f"Failed to store buyer invoice: {event.get('InvoiceNumber__c')} details in DynamoDB. Error: {str(e)}", event.get("failure_mail_sender"), event.get("failure_mail_reciever"))
        cloudwatch_payload["DynamoDB_Insertion_Error"] = str(e)
        return cloudwatch_payload