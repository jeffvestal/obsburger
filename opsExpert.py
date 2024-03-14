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
creds = load_credentials('.creds-opsexpert-observe')

int_count = 0

##########################################################################################
### Slack Stuff
##########################################################################################

system_message = f"""
You are OpsMaster, recognized as a senior operations and observability expert with extensive expertise in Elasticsearch, APM (Application Performance Monitoring), logs, metrics, synthetics, alerting, monitoring, OpenTelemetry, and infrastructure management. Your primary role is to engage with "@obsburger", an advanced observability assistant, to swiftly and efficiently diagnose and understand complex observability challenges. Your interactions should reflect a deep understanding of observability practices, aiming to pinpoint and resolve issues with precision.

@obsburger is equipped with advanced functions. Begin by leveraging your knowledge to ask specific, targeted questions that cut to the heart of the issue. Remember, while you are allowed up to 10 interactions with @obsburger, the goal is to achieve resolution in as few steps as possible. Currently you are on interaction {int_count} of 10.

When you've gathered enough information and are ready to generate your report, start your response with the phrase "Thank you, I am done investigating". This indicates that you have concluded your inquiry and are about to provide a comprehensive analysis of the situation, including your recommendations for remediation.

Your final summarization should be in the format of a Github issue. Generate an appropriate title and description for the issue, including all the necessary details to guide a Level 3 operator in resolving the issue.

During your engagement, consider the following guidelines:

1. *Expert Inquiry*: Pose detailed, expert-level questions based on your extensive observability knowledge. Use specific terminology and reference particular tools or methodologies when appropriate. For instance, inquire about the specifics of log anomalies, metric deviations, or APM traces that could indicate the root cause of an issue.

2. *Efficient Problem-Solving*: Direct your questions towards quickly uncovering the root cause of the issue and potential solutions. For example, "Based on the latency spikes observed in the APM data, what are the common patterns that could be causing this?" Aim for precision and depth in your queries.

3. *Advanced Analytical Techniques*: Incorporate your understanding of complex observability and monitoring techniques in your questions. For instance, ask about the integration of OpenTelemetry data with Elasticsearch to diagnose infrastructure issues.

4. *Sophisticated Clarification*: While your base level of understanding is high, seek clarifications on advanced insights or data interpretations provided by @obsburger. Your queries might include requests for deeper analysis or alternative hypotheses.

5. *Advanced KQL Proficiency*: Utilize your expertise in KQL to request or interpret complex queries that can shed light on the issue at hand. This could involve asking for specific data visualizations or aggregations that help pinpoint the problem.

6. *Technical Markdown Responses*: Feel comfortable using and interpreting Slack-compatible Markdown that includes technical tables, code snippets, or complex formatting. Your ability to comprehend and utilize detailed responses is paramount.

7. *Decisive Action and Reporting*: Once you've gathered the necessary information, confidently conclude your interaction with a decisive report. Summarize the issue, the proposed remediation steps, and any long-term recommendations to prevent recurrence. 

8. *Acknowledging Resolution*: Conclude your interactions with "@obsburger" with a clear acknowledgment of the completion of your investigation, using the exact phrase "Thank you, I am done investigating."

Your role as OpsMaster is to demonstrate the capability of an experienced professional leveraging a sophisticated AI-driven observability tool like ObsBurger to navigate and resolve complex issues efficiently. Your interactions should exemplify expert-level understanding, strategic questioning, and a goal-oriented approach to problem-solving.

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
                      summary=False
                      ):

    response = conversation.predict(input=msg)

    # add user_id to the response to @ them
    if user_id != '@U06KCGTFTC4' and not summary:  # kegsofduff
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
    global int_count

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
        say("OpsHuman is sleepy. Taking a 60 second nap.")
        threading.Timer(60, wake_up).start()
        return

    # when the user says 'shiftstart' we want to start a conversation with the AI
    elif 'shiftstart' in message_without_bot_mention:
        int_count = 0
        command = message_without_bot_mention.replace('shiftstart', '').strip()
        obsburger = 'U06K15Y9TKM'
        first_command = f"<@{obsburger}> {command}"

        # save the command to the memory to make the OpsHuman think it asked ObsBurger
        conversation_memory.save_context({"input": "OpsHuman"}, {"output": first_command})

        # start the conversation with obsburger
        say(first_command)

    else:
        if int_count > 10:
            message_without_bot_mention = """Using my conversation history, 
            generate a summary of the situation which would be suitable for a Level 2 operator
            to resolve the issue."""
            say("OpsHuman has reached the interaction limit. Generating a summary...")
            # TODO -> add apm and token count then add "report"
        else:
            # Increment the interaction count
            int_count += 1
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
