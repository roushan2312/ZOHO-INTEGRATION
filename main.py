from flask import Flask, request, jsonify
import boto3

cf = boto3.client("cloudformation")

app = Flask(__name__)

@app.route("/event", methods=["POST"])
def handle_event_route():
    event = request.get_json()
    try:
        stack_id = handle_event(event)
        return jsonify({"message": "Stack creation started", "stack_id": stack_id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def health():
    return "OK", 200

def handle_event(event):
    # event_id = event["org_id"]
    # stack_name = f"ZohoPluginCFN2-{event_id}"
    # template_url = "https://cfn-temp-zoho-plugin.s3.ap-south-1.amazonaws.com/cfn2.yaml"
    # params = [
    #     {"ParameterKey": "CustomerTableName", "ParameterValue": f"Customer-{event_id}"},
    #     {"ParameterKey": "InvoiceTableName", "ParameterValue": f"Invoice-{event_id}"},
    #     {"ParameterKey": "SecretName", "ParameterValue": f"ZohoPluginSecret-{event_id}"},
    #     {"ParameterKey": "ClientId", "ParameterValue": event["client_id"]},
    #     {"ParameterKey": "ClientSecret", "ParameterValue": event["client_secret"]},
    # ]
    # response = cf.create_stack(
    #     StackName=stack_name,
    #     TemplateURL=template_url,
    #     Parameters=params,
    #     Capabilities=["CAPABILITY_NAMED_IAM"]
    # )
    import requests
    client_id = "1000.DMZKLD5JA20XDVRL71F18K3BQAXUFJ"
    client_secret = "37cf537d6995959adb961a0b453695d9f194b47ed7"
    refresh_token = "1000.5974a44c4cc9ed017e2fe153d71629be.556b06a98ed94b69e346e3ae75722a26"
    url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://www.zoho.com/books",
        "grant_type": "refresh_token"
    }
    response = requests.post(url, data=data)
    # Optionally, you can print or log the response
    print("Zoho token response:", response.text)
    return response.text

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
