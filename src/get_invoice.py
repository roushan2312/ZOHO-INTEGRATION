from flask import jsonify
import requests
import boto3
from PyPDF2 import PdfReader, PdfWriter, PageObject
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

s3 = boto3.client("s3")

def create_header_pdf(header_text, width, height):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(width, height))
    can.setFont("Helvetica", 16)
    can.drawString(30, height - 30, header_text)
    can.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]

def create_annexure_pdf(annexure_data):
    """Create an Annexure page with a table from the provided data."""
    packet = io.BytesIO()
    doc = SimpleDocTemplate(packet, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    elements = []
    
    # Add "Annexure" heading
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.black,
        spaceAfter=20,
        alignment=1  # Center alignment
    )
    heading = Paragraph("Annexure", heading_style)
    elements.append(heading)
    elements.append(Spacer(1, 0.3*inch))
    
    # Check if annexure_data is a list of dicts
    if not annexure_data or not isinstance(annexure_data, list):
        packet.close()
        return None
    
    # Extract table data
    if len(annexure_data) > 0 and isinstance(annexure_data[0], dict):
        # Define header display name mapping
        header_display_names = {
            "shipmentName": "Shipment Number",
            "amount": "Amount",
            "techFeeAmount": "Tech Fee Amount",
            "orderSellerTechFee": "Tech Fee %",
        }
        
        # Define the desired column order
        column_order = ["shipmentName", "amount", "orderSellerTechFee", "techFeeAmount"]
        
        # Get headers from first dict keys
        original_headers = list(annexure_data[0].keys())
        
        # Reorder headers according to column_order, keeping any extra columns at the end
        headers = []
        for col in column_order:
            if col in original_headers:
                headers.append(col)
        # Add any remaining headers not in the predefined order
        for col in original_headers:
            if col not in headers:
                headers.append(col)
        
        # Transform headers for display
        display_headers = [header_display_names.get(header, header) for header in headers]
        
        # Create table data with display headers
        table_data = [display_headers]
        for row in annexure_data:
            table_data.append([str(row.get(header, "")) for header in headers])
        
        # Calculate column widths based on content length
        # col_widths = []
        # for col_idx, header in enumerate(headers):
        #     # Start with display header length
        #     max_length = len(str(display_headers[col_idx]))
        #     # Check all rows for this column
        #     for row in annexure_data:
        #         cell_value = str(row.get(header, ""))
        #         max_length = max(max_length, len(cell_value))
            
        #     # Calculate width: minimum 1 inch, maximum 3 inches, scale by character count
        #     # Approximate 0.08 inch per character
        #     width = min(max(1*inch, max_length * 0.08*inch), 3*inch)
        #     col_widths.append(width)
        
        # Create table
        # table = Table(table_data, colWidths=col_widths)
        table = Table(table_data, colWidths=[2*inch] * len(headers))
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        
        elements.append(table)
    
    # Build PDF
    doc.build(elements)
    packet.seek(0)
    return PdfReader(packet).pages[0] if packet.getvalue() else None

def get_invoice_function(event):
    client_id = event.get("client_id")
    client_secret = event.get("client_secret")
    refresh_token = event.get("refresh_token")
    org_id = event.get("org_id")
    # Accept either a Zoho invoice id (`invoice_id`) or a Salesforce invoice number (`invoice_number`).
    invoice_number = event.get("invoice_number")
    zoho_invoice_id = event.get("invoice_id")
    bucket_name = event.get("bucket_name")
    copies_raw = event.get("copies", 1)
    sf_invoice_id = event.get("sf_invoice_id")

    try:
        copies = int(copies_raw) if copies_raw is not None else 1
        if copies < 1:
            copies = 1
    except Exception:
        copies = 1

    # Validate required fields
    if not all([client_id, client_secret, refresh_token, org_id, invoice_number, bucket_name]):
        return {"error": "Missing required fields: client_id, client_secret, refresh_token, org_id, invoice_id/invoice_number, bucket_name"}, 400

    # Use the provided Salesforce invoice number for the S3 filename when available,
    # otherwise fall back to the Zoho invoice id.
    s3_name = invoice_number
    s3_key = f"invoices/{sf_invoice_id}_{s3_name}.pdf"
    generate_access_token_url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://www.zoho.in/books",
        "grant_type": "refresh_token"
    }

    token_response = requests.post(generate_access_token_url, data=data)
    if token_response.status_code != 200:
        return {"error": f"Token generation failed in get invoice function: {token_response.text}"}, 400

    access_token = token_response.json().get("access_token")
    if not access_token:
        return {"error": "No access token received in get invoice function"}, 400
    # Use the resolved invoice id (Zoho id or invoice number fallback) to request the PDF
    invoice_pdf_url = f"https://www.zohoapis.in/books/v3/invoices/{zoho_invoice_id}?organization_id={org_id}&accept=pdf"
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "X-com-zoho-organizationid": org_id
    }

    response = requests.get(invoice_pdf_url, headers=headers)
    if response.status_code != 200:
        return {"error": f"Failed to download PDF, Zoho get invoice api failed: {response.text}"}, 400

    # Verify we got PDF content
    if not response.content or len(response.content) == 0:
        return {"error": "Zoho API returned empty PDF content"}, 400

    original_pdf = io.BytesIO(response.content)
    try:
        reader = PdfReader(original_pdf)
        if len(reader.pages) == 0:
            return {"error": "No pages found in Zoho PDF"}, 400
    except Exception as pdf_error:
        return {"error": f"Failed to read PDF from Zoho: {str(pdf_error)}"}, 400
    
    writer = PdfWriter()

    # Extract all pages once to avoid iterator issues
    pages = list(reader.pages)
    
    header_labels = ["Original", "Duplicate", "Triplate", "Quadruplicate", "Quintuplicate", "Sextuplicate"]
    for copy_num in range(copies):
        label = header_labels[copy_num] if copy_num < len(header_labels) else f"Copy {copy_num+1}"
        for page in pages:
            # Re-read the page from original PDF each time to avoid modification issues
            reader_copy = PdfReader(io.BytesIO(response.content))
            current_page = reader_copy.pages[pages.index(page)]
            
            # Get page size
            width = float(current_page.mediabox.width)
            height = float(current_page.mediabox.height)
            # Create header page
            header_page = create_header_pdf(label, width, height)
            # Merge header onto the original page directly
            current_page.merge_page(header_page)
            writer.add_page(current_page)
        
        # Add Annexure page once per copy (if needed only on first copy, move outside loop)
        if copy_num == 0:  # Add annexure only once
            annexure_data = event.get("annexure_data")
            if annexure_data:
                try:
                    annexure_page = create_annexure_pdf(annexure_data)
                    if annexure_page:
                        writer.add_page(annexure_page)
                        print("Annexure page added to PDF")
                except Exception as e:
                    print(f"Warning: Failed to add annexure page: {str(e)}")

    output_pdf = io.BytesIO()
    writer.write(output_pdf)
    output_pdf.seek(0)

    # Upload to S3
    try:
        pdf_content = output_pdf.getvalue()
        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=pdf_content,
            ContentType="application/pdf"
        )
        return {
            "message": f"Invoice PDF ({copies} copies) uploaded successfully",
            "s3_location": f"{event.get('invoice_url_prefix')}/{s3_key}"
        }, 200
    except Exception as s3_error:
        return {"error": f"S3 upload failed: {str(s3_error)}"}, 400