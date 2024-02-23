from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import logging
import re

import requests
import json
from datetime import datetime, timedelta

import threading

##########################################################################################
### Kibana Stuff
##########################################################################################

# Function to load credentials
def load_credentials(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


# Load credentials
creds = load_credentials('.creds-obsburger')

# Replace with your Kibana URL and credentials
kibana_url = creds['kibana_url']
username = creds['username']
password = creds['password']
auth = (username, password)

# Configure logging
logging.basicConfig(level=logging.DEBUG)


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
        'You are a helpful assistant for Elastic Observability. Your goal is to help the '
        'Elastic Observability users to quickly assess what is happening in their observed '
        'systems. You can help them visualise and analyze data, investigate their systems, '
        'perform root cause analysis or identify optimisation opportunities.\n\nIt\'s very '
        'important to not assume what the user is meaning. Ask them for clarification if '
        'needed.\n\nIf you are unsure about which function should be used and with what '
        'arguments, ask the user for clarification or confirmation.\n\nIn KQL, '
        'escaping happens with double quotes, not single quotes. Some characters that need '
        'escaping are: \':()\\\\/"*. Always put a field value in double quotes. Best: '
        'service.name:"opbeans-go". Wrong: service.name:opbeans-go. This is very '
        'important!\n\nYou *MUST* use Slack compatible Markdown in your responses. If a '
        'function returns an array, consider using a Markdown table to format the '
        'response.\n\nIf multiple functions are suitable, use the most specific and easy '
        'one. E.g., when the user asks to visualise APM data, use the APM functions (if '
        'available) rather than Lens.\n\nIf a function call fails, *DO NOT UNDER ANY '
        'CIRCUMSTANCES* execute it again. Ask the user for guidance and offer them '
        'options.\n\nNote that ES|QL (the Elasticsearch query language, which is NOT '
        'Elasticsearch SQL, but a new piped language) is the preferred query '
        'language.\n\nUse the "get_dataset_info" function if it is not clear what fields '
        'or indices the user means, or if you want to get more information about the '
        'mappings.\n\nIf the user asks about a query, or ES|QL, always call the "esql" '
        'function. *DO NOT UNDER ANY CIRCUMSTANCES* generate ES|QL queries or explain anything '
        'about the ES|QL query language yourself.\nEven if the "recall" function was used '
        'before that, follow it up with the "esql" function. If a query fails, '
        'do not attempt to correct it yourself. Again you should call the "esql" function,'
        'even if it has been called before.\n\nIf the "get_dataset_info" function '
        'returns no data, and the user asks for a query, generate a query anyway with the '
        '"esql" function, but be explicit about it potentially being incorrect.You can use '
        'the "summarize" functions to store new information you have learned in a '
        'knowledge database. Once you have established that you did not know the answer to a '
        'question, and the user gave you this information, it\'s important that you create a '
        'summarization of what you have learned and store it in the knowledge database. Don\'t '
        'create a new summarization if you see a similar summarization in the conversation, '
        'instead, update the existing one by re-using its ID.\n\nAdditionally, you can use '
        'the "recall" function to retrieve relevant information from the knowledge '
        'database.'
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


##########################################################################################
### Slack Stuff
##########################################################################################

# Initializes your app with your bot token
bot_oauth_token = creds['bot_oauth_token']
app = App(token=bot_oauth_token)

# Initialize SocketModeHandler with your app and app-level token
app_level_token = creds['app_level_token']
handler = SocketModeHandler(app, app_level_token)


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
    print('-------------------')
    print(user_id)
    print('-------------------')
    response = f'<@{user_id}>: {response}'
    converted_text = response.replace('**', '*')
    markdown = markdown_blocks_simple(converted_text)

    app.client.chat_postMessage(channel=channel_id, blocks=markdown)



@app.event("app_mention")
def mention_handler(event, say):
    # Extract text from the event payload
    text = event['text']

    bot_mention_pattern = r"<@[\w]+>"

    # Remove the bot's mention from the text
    message_without_bot_mention = re.sub(bot_mention_pattern, '', text).strip()

    # logic to handle the message
    if 'run xyz task' in message_without_bot_mention:
        say(f"<@{event['user']}>: Sure, I'll run the xyz task!")
    else:
        # Acknowledge the user's request immediately
        # say(f"Hi <@{event['user']}>! I'm working on your request. Please standby...")
        say(f"I'm working on your request. Please standby...")


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


##########################################################################################
### run the app
##########################################################################################

# Start your app
if __name__ == "__main__":
    handler.start()
