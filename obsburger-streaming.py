# vestal

import re
import io
import json
import logging
import requests
import threading

from datetime import datetime, timedelta
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


conversation = {
    'id': None,
    'response': None,
    'messages': []
}
lock = threading.Lock()


def update_conversation(key, value):
    global conversation
    with lock:  # Acquire lock
        # conversation = value

        conversation[key] = value

        print(f'Updated conversation: {conversation}')
    # Updated conversation: {'title': 'Recent Alerts in Elastic Observability for the Past 48 Hours',
    # 'id': 'f7e5200b-516e-4d31-b8cd-a22423b09ca1', 'last_updated': '2024-02-23T14:36:03.181Z'}


##########################################################################################
### Kibana Stuff
##########################################################################################

# Function to load credentials
def load_credentials(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


# Load credentials
creds = load_credentials('.creds-obsburger-eden')

# Replace with your Kibana URL and credentials
kibana_url = creds['kibana_url']
username = creds['username']
password = creds['password']
auth = (username, password)

# Configure logging
logging.basicConfig(level=logging.INFO)


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


# Get the GenAI connector id
connector_id = getGenAIConnectorId(kibana_url, auth)


def getKibanaVersion(kibana_url, auth):
    """Obtains the Kibana Version from the Kibana API

    Args:
      (str) kibana_url: URL to Kibana instance
      ((str, str)) auth: tuple (username, password) to access Kibana

    Returns:
      (str) Kibana Version as a string (e.g. 8.14.0)
    """
    headers = {
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    url_connector = f"{kibana_url}/api/status"
    status = requests.get(url=url_connector, headers=headers, auth=auth, verify=True)
    version = status.json()["version"]["number"]
    return version


# noinspection PyTypeChecker
def getAssistantsResponse(kibana_url,
                          auth,
                          connector_id,
                          user_question,
                          persist_conversation=True,
                          # conversation={}`,
                          streaming=True,  # Always True
                          ):
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
        "messages": [],
        "connectorId": connector_id,
        "persist": persist_conversation,
    }

    # if persist_conversation and conversation != {}:
    if persist_conversation and not conversation['id'] is None:
        data["conversationId"] = conversation["id"]

    version = getKibanaVersion(kibana_url, auth)

    url = f"{kibana_url}/internal/observability_ai_assistant/chat/complete"

    # if conversation == {}:
    if conversation['id'] is None:
        system_message = {
            "@timestamp": (datetime.now() - timedelta(minutes=2)).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ),
            "message": {
                "role": "system",
                "content": assistant_system_message,
            },
        }
        data["messages"].append(system_message)
    else:
        system_message = None
        data["messages"] = data["messages"] + conversation["messages"]

    user_message = {
        "@timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        "message": {
            "role": "user",
            "content": user_question,
        },
    }
    data["messages"].append(user_message)

    data = json.dumps(data)

    response_array = []
    with requests.post(url=url, headers=headers, auth=auth, verify=True, data=data, stream=True) as response:
        try:
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:  # Ignore keep-alive new lines
                        response_json = json.loads(line.decode("utf-8"))
                        response_array.append(response_json)
                        yield response_json
                        # yield line.decode('utf-8')
            else:
                yield f"ERROR: Response status code {response.status_code}"
        except Exception as e:
            yield f"ERROR: {str(e)}"

    # handle conversation persistence
    messages = [r["message"] for r in response_array if r["type"] == "messageAdd"]

    if not conversation['messages']:
        messages = [system_message, user_message] + messages
        # update_conversation_id('messages', messages)
    else:
        messages = conversation["messages"] + [user_message] + messages
        # update_conversation_id('messages', messages)
    update_conversation('messages', messages)

    if not persist_conversation:
        message_index = -1
    else:
        message_index = -2

    try:
        assistant_response = response_array[message_index]["message"]["message"][
            "content"
        ]

        update_conversation('response', assistant_response)
    except:
        print(f"Response was not successful: {response.text}")
        update_conversation('id', None)


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


# def handle_message(event, say):

def long_running_task(channel_id, user_id, msg, kb_url, ath, conn_id):
    for response_line in getAssistantsResponse(kb_url,
                                               ath,
                                               conn_id,
                                               msg
                                               ):
        try:
            # Parse the line as JSON
            response_json = response_line
            print(response_json)

            # Check the type of the message
            if response_json.get("type") == "chatCompletionChunk":
                # Chunks can't be used for streaming in Slack
                continue

            # print()

            if response_json.get('type') == 'conversationCreate':
                # update_conversation(response_json.get('conversation'))
                update_conversation('id', response_json.get('conversation').get('id'))

            # For large responses the assistant is going to process, sent as snippet
            elif response_json.get('message').get('message').get('role') == 'user' and response_json.get(
                    'message').get('message').get('content') != "[]":
                content_str = response_json.get('message').get('message').get('content')
                # Try to load the string as JSON and pretty-print it
                try:
                    parsed_json = json.loads(content_str)
                    pretty_content = json.dumps(parsed_json, indent=4)
                except json.JSONDecodeError:
                    # If content_str is not valid JSON, use the original string
                    pretty_content = content_str

                # Encode the pretty printed JSON string to bytes
                file_content = io.BytesIO(pretty_content.encode('utf-8'))

                app.client.files_upload(channels=channel_id,
                                        file=file_content,
                                        title="Elastic Observability AI Assistant",
                                        initial_comment=f"Function _{response_json.get('message').get('message').get('name')}_ Elastic Observability AI Assistant... Processing...",
                                        filetype="json",
                                        )
            else:
                # Should be the final response from the assistant, so @ the user
                if response_json.get('message').get('message').get('content') not in ["[]", "", None]:
                    # Format the message for Slack
                    content = f"{response_json.get('message').get('message').get('content')}"
                    formatted_message = f'<@{user_id}>: {content}'
                    converted_text = formatted_message.replace('**', '*')  # Slack markdown conversion

                # Intermittent messages from the assistant showing status updates
                elif response_json.get('message').get('message').get('role') == 'assistant' and response_json.get(
                        'message').get('message').get('function_call') is not None:
                    # Format the message for Slack
                    role = response_json.get('message').get('message').get('role')
                    function_name = response_json.get('message').get('message').get('function_call').get('name')
                    function_arguments = response_json.get('message').get('message').get('function_call').get(
                        'arguments')

                    formatted_message = f'{role} is calling function: `{function_name}: {function_arguments}`'
                    converted_text = formatted_message.replace('**', '*')

                # Convert the message to Slack markdown
                markdown = markdown_blocks_simple(converted_text)
                # Send the message to Slack
                app.client.chat_postMessage(channel=channel_id, blocks=markdown, text=converted_text)
        except json.JSONDecodeError:
            # Handle the case where the response line is not valid JSON
            print(f"Invalid JSON received: {response_line}")
        except KeyError:
            # Handle missing keys in the JSON
            print(f"KeyError encountered while processing line: {response_line}")
        except AttributeError:
            print(f"AttributeError encountered while processing json: \n{response_json}")


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
                               connector_id

                               )
                         ).start()


# Log all events received
# noinspection PyTypeChecker
@app.event({"type": re.compile(".*")})
def log_all_events(event, logger):
    logger.debug(f"Received event: {event}")


##########################################################################################
### run the app
##########################################################################################

# Start your app
if __name__ == "__main__":
    handler.start()
