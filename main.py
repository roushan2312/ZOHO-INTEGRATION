from flask import Flask, request, jsonify
import boto3
from create_logic import run_create
from customer_logic import run_customer
from update_logic import run_update

cf = boto3.client("cloudformation")

app = Flask(__name__)

@app.route("/event", methods=["POST"])
def handle_event_route():
    event = request.get_json()
    try:
        status = event.get("status")
        if status == "create":
            result = run_create(event)
        elif status == "customer":
            result = run_customer(event)
        elif status == "update":
            result = run_update(event)
        else:
            return jsonify({"error": "Invalid status"}), 400
        return jsonify({"message": result}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
