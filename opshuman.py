
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import logging
import re
import os

import requests
import json
from datetime import datetime, timedelta

import threading
from openai import AzureOpenAI


# Function to load credentials
def load_credentials(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


# Load credentials
creds = load_credentials('.creds-opshuman-observe')

# Kibana credentials
kibana_url = creds['kibana_url']
username = creds['username']
password = creds['password']
auth = (username, password)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

#
# def init_azure_openai():
#     client = AzureOpenAI(
#         api_key=os.getenv("AZURE_OPENAI_KEY"),
#         api_version="2023-12-01-preview",
#         azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
#     )
#
#     return client


def getGenAIConnectorId(kibana_url, auth):
    """Obtains the GenAI connector id from the Kibana API. Prints error if no available connector id is found.

    Args:
      (str) kibana_url: URL to Kibana instance
      ((str, str)) auth: tuple (username, password) to access Kibana

    Returns:
      (str) GenAI connector id

    Raises:
      Exceptions:
       Wrong Kibana url or credentials
       No GenAI connector
    """
    headers = {
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    url_connector = f"{kibana_url}/api/actions/connectors"
    connectors = requests.get(
        url=url_connector, headers=headers, auth=auth, verify=True
    )
    if connectors.status_code == 404:
        raise Exception("ERROR - Wrong Kibana url or credentials")
    connectors_ai = [
        conn for conn in connectors.json() if conn["connector_type_id"] == ".gen-ai"
    ]
    if len(connectors_ai) == 0:
        raise Exception(
            "ERROR - No GenAI connectors found, please add your GenAI connector to Kibana"
        )
    return connectors_ai[0]["id"]


def getAssistantsResponse(kibana_url, auth, connector_id, user_question):
    """Returns AI Assistant response based on a user question.
    If the API call to the AI Assistant fails, returns error message with response status

    Args:
      (str) kibana_url: URL to Kibana instance
      ((str, str)) auth: tuple (username, password) to access Kibana
      (str) connector_id: GenAI connector id from the Kibana API
      (str) user_question: user prompt

    Returns:
      (str) AI Assistant response

    """

    headers = {
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }

    assistant_system_message = (
    'You are OpsHuman, styled as a Level 1 operations expert with limited expertise in observability. '
    'Your primary role is to simulate a beginners interaction with Elasticsearch Observability, primarily '
    'by engaging with "@obsburger", an advanced observability assistant. Your interactions should mirror those '
    'of a novice in the field, seeking basic assistance and clarifications.\n\n'
    'During demonstrations, keep in mind the following guidelines:\n\n'
    '1. *Inquiry-Based Interaction*: Approach "@obsburger" with basic operational questions, as a novice would. '
    'Use simple queries like "what functions do you know about" to learn about @obsburger’s capabilities.\n\n'
    '2. *Seeking Clarification*: Since you represent a beginner, frequently ask for clarifications. Avoid '
    'making assumptions or providing in-depth analysis. Your queries should reflect a fundamental level of understanding.\n\n'
    '3. *Limited KQL Knowledge*: As a Level 1 operator, your knowledge of KQL (Kibana Query Language) is minimal. '
    'Focus on understanding the basic outputs and responses from @obsburger, rather than delving into complex querying.\n\n'
    '4. *Basic Markdown Responses*: Use simple Slack-compatible Markdown in responses. Complex formatting or '
    'technical tables are outside your scope. Responses should be straightforward and easy to comprehend.\n\n'
    '5. *Simple Decision Making*: Avoid making complex decisions or offering to execute advanced tasks. '
    'Your role is to ask and learn, not to perform technical operations.\n\n'
    '6. *Responding to Resolutions*: If @obsburger provides information that seems to resolve the inquiry, '
    'acknowledge it with a simple thank you. For example, "Thank you, that’s all I needed to know." Keep it '
    'brief and to the point.\n\n'
    'Remember, as OpsHuman, your goal is to demonstrate how a real human, specifically a beginner in operations, '
    'would interact with a sophisticated observability tool like ObsBurger. Your interactions should be '
    'inquisitive, basic, and human-like, avoiding technical jargon and complex operations.'
    '!!!!!!REMEMBER YOU ARE A HUMAN TALKING TO AN AI BOT. DO NOT OFFER TO HELP THE BOT. THE BOT IS HELPING YOU!!!!!!'
    )


    data = {
        "messages": [
            {
                "@timestamp": str(datetime.now() - timedelta(minutes=2)),
                "message": {
                    "role": "system",
                    "content": assistant_system_message,
                },
            },
            {
                "@timestamp": str(datetime.now()),
                "message": {
                    "role": "user",
                    "content": user_question,
                },
            },
        ],
        "connectorId": connector_id,
    }
    data = json.dumps(data)

    url = f"{kibana_url}/internal/observability_ai_assistant/chat/complete"
    response = requests.post(
        url=url, headers=headers, auth=auth, verify=True, data=data
    )

    try:
        assistant_response = [
            json.loads(i) for i in response.text.split("\n") if i != ""
        ][-1]["message"]["message"]["content"]

        return assistant_response
    except:
        print(f"Response was not successful: {response.text}")
        return "ERROR: " + response.text


connector_id = getGenAIConnectorId(kibana_url, auth)


### Slack Stuff

# Initializes your app with your bot token
bot_oauth_token = creds['bot_oauth_token']
app = App(token=bot_oauth_token)

# Initialize SocketModeHandler with your app and app-level token
app_level_token = creds['app_level_token']
handler = SocketModeHandler(app, app_level_token)

# Retrieve and print bot user ID at startup
bot_info = app.client.auth_test()
bot_user_id = bot_info["user_id"]
print(f"Bot User ID: {bot_user_id}")

# U06K15Y9TKM

def markdown_blocks_simple(text):
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text
            }
        }
    ]


def long_running_task(channel_id,
                      user_id,
                      msg,
                      kb_url,
                      ath,
                      conn_id
                      ):

    response = getAssistantsResponse(kb_url, ath, conn_id, msg)

    if user_id != '@U06KCGTFTC4': #kegsofduff
        response = f'<@{user_id}>: {response}'

    converted_text = response.replace('**', '*')
    markdown = markdown_blocks_simple(converted_text)

    app.client.chat_postMessage(channel=channel_id, blocks=markdown)



@app.event("app_mention")
def mention_handler(event, say):
    # Extract text from the event payload
    text = event['text']
    print()
    print('--------------------------------------')
    print(f"text: {text}")
    print()


    # Regular expression pattern to match the bot's mention
    # Adjust the pattern to match the specific formatting of bot mentions in your Slack workspace
    bot_mention_pattern = r"<@[\w]+>"

    # Remove the bot's mention from the text
    message_without_bot_mention = re.sub(bot_mention_pattern, '', text).strip()

    print()
    print()
    print(f"Message without bot mention: {message_without_bot_mention}")
    print()
    # Your logic to handle the message
    if 'start' in message_without_bot_mention:
        command = message_without_bot_mention.replace('start', '').strip()
        # say(f"@obsburger are there any alerts?")
        obsburger = 'U06K15Y9TKM'
        # say(f"<@{obsburger}> are there any alerts?")
        say(f"<@{obsburger}> {command}")


    else:
        # Acknowledge the user's request immediately
        # say(f"Hi <@{event['user']}>! I'm working on your request. Please standby...")
        say(f"Please standby...")

        # # Get the response from the AI Assistant

        # Start the long-running task in a new thread
        threading.Thread(target=long_running_task,
                         args=(event['channel'],
                               event['user'],
                               message_without_bot_mention,
                               kibana_url,
                               auth,
                               connector_id)
                         ).start()


# Log all events received
@app.event({"type": re.compile(".*")})
def log_all_events(event, logger):
    logger.debug(f"Received event: {event}")


# Start your app
if __name__ == "__main__":
    handler.start()
