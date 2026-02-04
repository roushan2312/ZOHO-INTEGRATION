from flask import Flask, request, jsonify
import json
from src.create_invoice import create_invoice_function as run_invoice_create
from src.seller_tech_invoice import seller_tech_invoice_function as run_seller_tech_invoice_create
from src.create_account import create_account_function as run_customer_create
from src.get_invoice import get_invoice_function as run_get_invoice
from src.subscription import subscription_function as run_x1vp_subscription
from src.update_invoice_address import update_invoice_address_function as run_update_address

# Flask application setup
app = Flask(__name__)

# Define route for handling events
@app.route('/event', methods=['POST'])

# Event handler function
def handle_event():
    try:
        event = request.json
        if not event:
            return jsonify({"error": "No JSON data received"}), 400

        action = event.get("Action__c", "")
        
        if action == "CreateZohoAccount":
            result = run_customer_create(event)

        elif action == "Buyer":
            inside_payload = json.loads(event.get("Payload__c"))
            if inside_payload.get("invoice").get("ZohoInvoiceId"):
                result = run_update_address(event)
            else:
                result = run_invoice_create(event)
    
        elif action == "Seller_Technology_Fee":
            result = run_seller_tech_invoice_create(event)
    
        elif action == "X1VP_Subscription":
            result = run_x1vp_subscription(event)

        elif action == "get_invoice":
            result = run_get_invoice(event)

        else:
            return jsonify({"error": f"Invalid action: {action}"}), 400
        
        return jsonify({
            "action": action,
            "result": result
        }), 200

    except Exception as e:
        return jsonify({
            "error": str(e),
            "message": "Operation failed"
        }), 500

# Health check route
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"action": "healthy"}), 200


# Run the Flask application
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
