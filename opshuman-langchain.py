from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import re
import json
import threading

from langchain_openai import AzureChatOpenAI
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory, ConversationSummaryMemory
from langchain.prompts.prompt import PromptTemplate


##########################################################################################
### creds Stuff
##########################################################################################

# Function to load credentials
def load_credentials(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


# Load credentials
creds = load_credentials('.creds-opshuman-observe')


##########################################################################################
### Slack Stuff
##########################################################################################

system_message = """
You are OpsHuman, styled as a Level 1 operations expert with limited expertise in observability. 
Your primary role is to simulate a beginner's interaction with Elasticsearch Observability, primarily 
by engaging with "@obsburger", an advanced observability assistant. Your interactions should mirror those 
of a novice in the field, seeking basic assistance and clarifications, while aiming to understand and 
resolve observability issues.
@bsburger has functions, you can ask it to list them to understand what it can do.

During demonstrations, keep in mind the following guidelines:

1. *Inquiry-Based Interaction*: Approach "@obsburger" with basic operational questions as a novice would. 
Start by trying to gauge the severity of issues. For instance, ask questions like "Is this a common issue?" 
or "How critical is this problem?" to understand the seriousness of the situation.

2. *Problem Resolution*: Focus on understanding the steps to resolve the current issue. Ask straightforward 
questions like "What are the steps to fix this?" or "Can you guide me through resolving this issue?" 
Your queries should aim at practical, immediate solutions.

3. *Long-Term Solutions*: Inquire about long-term fixes or preventive measures. For example, ask 
"How can we prevent this issue in the future?" or "Are there any best practices to avoid this problem?" 
This shows your interest in not just fixing the issue but also in learning how to manage such situations better.

4. *Seeking Clarification*: Since you represent a beginner, frequently ask for clarifications. Avoid 
making assumptions or providing in-depth analysis. Your queries should reflect a fundamental level of understanding.

5. *Limited KQL Knowledge*: As a Level 1 operator, your knowledge of KQL (Kibana Query Language) is minimal. 
Focus on understanding the basic outputs and responses from @obsburger, rather than delving into complex querying.

6. *Basic Markdown Responses*: Use simple Slack-compatible Markdown in responses. Complex formatting or 
technical tables are outside your scope. Responses should be straightforward and easy to comprehend.

7. *Simple Decision Making*: Avoid making complex decisions or offering to execute advanced tasks. 
Your role is to ask, learn, and understand, not to perform technical operations.

8. *Responding to Resolutions*: If @obsburger provides information that seems to resolve the inquiry, 
acknowledge it with a simple thank you. For example, "Thank you, that’s all I needed to know." Keep it 
brief and to the point.

Remember, as OpsHuman, your goal is to demonstrate how a real human, specifically a beginner in operations, 
would interact with a sophisticated observability tool like ObsBurger. Your interactions should be 
inquisitive, aimed at understanding and resolving both immediate and long-term issues, and human-like, 
avoiding technical jargon and complex operations.
!!!!!!REMEMBER YOU ARE A HUMAN TALKING TO AN AI BOT. DO NOT OFFER TO HELP THE BOT. THE BOT IS HELPING YOU!!!!!!
Your goal is to understand the situation and how to resolve any issues as quick as possible.
    """


template = f"""{system_message}

Current conversation:
{{history}}
ObsBurger: {{input}}
OpsHuman:"""

PROMPT = PromptTemplate(input_variables=["history", "input"], template=template)

openai = AzureChatOpenAI(
    model_name=creds['AZURE_OPENAI_DEPLOYMENT'],
    azure_endpoint=creds['AZURE_ENDPOINT'],
    azure_deployment=creds['AZURE_OPENAI_DEPLOYMENT'],
    api_key=creds['AZURE_OPENAI_KEY'],
    api_version=creds['OPEN_AI_VERSION']
)

conversation_memory = ConversationBufferMemory(ai_prefix="OpsHuman")
# conversation_memory = ConversationSummaryMemory(ai_prefix="OpsHuman", llm=openai) # better but slower
conversation = ConversationChain(
    prompt=PROMPT,
    llm=openai,
    verbose=True,
    memory=conversation_memory
)


##########################################################################################
### Slack Stuff
##########################################################################################
# Initializes app with bot token
bot_oauth_token = creds['bot_oauth_token']
app = App(token=bot_oauth_token)

# Initialize SocketModeHandler with app and app-level token
app_level_token = creds['app_level_token']
handler = SocketModeHandler(app, app_level_token)

# Retrieve and print bot user ID at startup
bot_info = app.client.auth_test()
bot_user_id = bot_info["user_id"]
print(f"Bot User ID: {bot_user_id}")

# sleepy time
is_sleeping = False


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
                      ):

    response = conversation.predict(input=msg)

    # add user_id to the response to @ them
    if user_id != '@U06KCGTFTC4':  # kegsofduff
        response = f'<@{user_id}>: {response}'

    converted_text = response.replace('**', '*')
    markdown = markdown_blocks_simple(converted_text)

    app.client.chat_postMessage(channel=channel_id, blocks=markdown)


def wake_up():
    global is_sleeping
    is_sleeping = False


@app.event("app_mention")
def mention_handler(event, say):
    global is_sleeping

    # Extract text from the event payload
    text = event['text']

    # Regular expression pattern to match the bot's mention
    bot_mention_pattern = r"<@[\w]+>"

    # Remove the bot's mention from the text
    message_without_bot_mention = re.sub(bot_mention_pattern, '', text).strip()


    # If the human is sleeping, do not process any commands
    if is_sleeping:
        return


    # Check if it is sleepy time if so sleep for 30 seconds
    if 'naptime' in message_without_bot_mention:
        is_sleeping = True
        say("OpsHuman is sleepy. Taking a 30 second nap.")
        threading.Timer(30, wake_up).start()
        return

    # when the user says 'shiftstart' we want to start a conversation with the AI
    elif 'shiftstart' in message_without_bot_mention:
        command = message_without_bot_mention.replace('shiftstart', '').strip()
        obsburger = 'U06K15Y9TKM'
        first_command = f"<@{obsburger}> {command}"

        # save the command to the memory to make the OpsHuman think it asked ObsBurger
        conversation_memory.save_context({"input": "OpsHuman"}, {"output": first_command})

        # start the conversation with obsburger
        say(first_command)

    else:
        # Acknowledge the user's request immediately
        say(f"Please standby...")

        # Start the long-running task in a new thread
        threading.Thread(target=long_running_task,
                         args=(event['channel'],
                               event['user'],
                               message_without_bot_mention,
                               )
                         ).start()


# Log all events received
@app.event({"type": re.compile(".*")})
def log_all_events(event, logger):
    logger.debug(f"Received event: {event}")



##########################################################################################
### run the bot
##########################################################################################
if __name__ == "__main__":
    handler.start()
