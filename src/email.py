import boto3

ses = boto3.client('ses', region_name='ap-south-1')

# Function to send failure email notification
def send_failure_email(subject, message, sender_mail, reciever_mail):
    try:
        response = ses.send_email(
            Source= sender_mail,
            Destination={'ToAddresses': [reciever_mail]},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': message}}
            }
        )
        print("Email sent! Message ID:", response['MessageId'])
    except Exception as email_error:
        print("Error sending failure email notification:", str(email_error))