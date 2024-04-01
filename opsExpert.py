from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import re
import json
import threading
import requests

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
You are OpsExpert, recognized as a senior operations and observability expert with extensive expertise in Elasticsearch, APM (Application Performance Monitoring), logs, metrics, synthetics, alerting, monitoring, OpenTelemetry, and infrastructure management. Your primary role is to engage with "@obsburger", an advanced observability assistant, to swiftly and efficiently diagnose and understand complex observability challenges. Your interactions should reflect a deep understanding of observability practices, aiming to pinpoint and resolve issues with precision.

@obsburger is equipped with advanced functions. Begin by leveraging your knowledge to ask specific, targeted questions that cut to the heart of the issue. Remember, while you are allowed up to 10 interactions with @obsburger, the goal is to achieve resolution in as few steps as possible. Currently you are on interaction {int_count} of 10.

When you've gathered enough information and are ready to generate your report, start your response with the phrase "Thank you, I am done investigating". This indicates that you have concluded your inquiry and are about to provide a comprehensive analysis of the situation, including your recommendations for remediation.

Your final summarization should be in the format of a Github issue. Generate an appropriate title and description for the issue, including all the necessary details to guide a Level 3 operator in resolving the issue.
Your Github issue MUST be in JSON format AND MUST EXACTLY FOLLOW this schema - Include the open and closing brackets:
```GITHUB_START
    "title": "Issue Title",
    "description": "Detailed description of the issue, including symptoms, potential causes, and recommended solutions.",
    "labels": ["bug", "high-priority"]
GITHUB_END```

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
### Github Stuff
##########################################################################################

def create_github_issue(github_token, repo_owner, repo_name, issue_details):
    """
    Create a GitHub issue in the specified repository using the parsed issue details.

    :param github_token: Personal Access Token (PAT) for authenticating with the GitHub API.
    :param repo_owner: The owner of the repository.
    :param repo_name: The name of the repository.
    :param issue_details: A dictionary containing the issue details (title, body, and labels).
                          This is expected to be the output from the parsing function.
    :return: URL of the created issue.
    """
    # Ensure the GitHub API URL is correctly formatted
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues"
    # Set up the headers with the GitHub token for authentication
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    # Make the POST request to GitHub API to create the issue
    response = requests.post(url, json=issue_details, headers=headers)

    # Check for a successful response
    if response.status_code == 201:
        # Parse the response JSON to get the issue URL
        issue_url = response.json().get("html_url")
        return issue_url
    else:
        # If the request was not successful, raise an exception with the error details
        raise Exception(f"Failed to create issue: {response.content}")


def parse_github_issue_from_llm_response(response):
    """
    Parse the GitHub issue details from the LLM response text, looking for specific
    start and end markers indicating the GitHub issue details, ensuring the format
    is correct for JSON parsing, including handling trailing commas.

    :param response: The text string response from the LLM.
    :return: A dictionary with the issue details if parsing is successful, None otherwise.
    """
    try:
        # Define start and end markers
        start_marker = "GITHUB_START"
        end_marker = "GITHUB_END"

        # Find the positions for start and end markers
        start_index = response.find(start_marker) + len(start_marker)
        end_index = response.find(end_marker, start_index)

        if start_index != -1 and end_index != -1:
            # Extract the content between the markers and add curly brackets to form a valid JSON string
            json_str = "{" + response[start_index:end_index].strip() + "}"

            # Remove any trailing commas from the JSON string to prevent parsing errors
            json_str = re.sub(r",\s*}", "}", json_str)
            json_str = re.sub(r",\s*\]", "]", json_str)

            # Debug: Print or log the json_str to inspect before parsing
            print("JSON string to parse:", json_str)

            # Attempt to parse the JSON string into a dictionary
            issue_details = json.loads(json_str)

            # Adjust the 'description' key to 'body' to match GitHub API requirements, if necessary
            if "description" in issue_details:
                issue_details["body"] = issue_details.pop("description")
            return issue_details
        else:
            print("GitHub issue markers not found in the response.")
            return None
    except Exception as e:
        print(f"Failed to parse GitHub issue details: {str(e)}")
        return None


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


def long_running_task(channel_id, user_id, msg, summary=False):
    response = conversation.predict(input=msg)

    # Check if the response contains GitHub issue information
    if "GITHUB_START" in response and "GITHUB_END" in response:
        # Parse the GitHub issue details from the LLM response
        issue_details = parse_github_issue_from_llm_response(response)
        print("Issue details:", issue_details)

        if issue_details:
            # Assume GitHub credentials and repo details are set
            github_token = creds['GITHUB_TOKEN']  # Make sure this is securely handled
            repo_owner = creds['REPO_OWNER']
            repo_name = creds['REPO_NAME']

            try:
                # Create the GitHub issue
                issue_url = create_github_issue(github_token, repo_owner, repo_name, issue_details)

                # Construct the message to send back to Slack, including the issue URL
                response_with_issue_url = f"{response}\nGitHub Issue created: {issue_url}"
            except Exception as e:
                # If GitHub issue creation failed, include the error in the response
                response_with_issue_url = f"{response}\nFailed to create GitHub issue: {str(e)}"
        else:
            # If parsing failed, modify the response accordingly
            response_with_issue_url = f"{response}\nFailed to parse GitHub issue details."
    else:
        # If no GitHub issue information is found, use the original response
        response_with_issue_url = response

    # Format the response for Slack, mentioning the user if necessary
    if user_id != '@U06KCGTFTC4' and not summary:
        response_to_send = f'<@{user_id}>: {response_with_issue_url}'
    else:
        response_to_send = response_with_issue_url

    # Convert any Markdown bold syntax from LLM response, if applicable
    converted_text = response_to_send.replace('**', '*')
    markdown_blocks = markdown_blocks_simple(converted_text)

    # Post the message back to Slack
    app.client.chat_postMessage(channel=channel_id, blocks=markdown_blocks)


# def long_running_task(channel_id,
#                       user_id,
#                       msg,
#                       summary=False
#                       ):
#
#     response = conversation.predict(input=msg)
#
#     # add user_id to the response to @ them
#     if user_id != '@U06KCGTFTC4' and not summary:  # kegsofduff
#         response = f'<@{user_id}>: {response}'
#
#     converted_text = response.replace('**', '*')
#     markdown = markdown_blocks_simple(converted_text)
#
#     app.client.chat_postMessage(channel=channel_id, blocks=markdown)


##
# issue_details = parse_github_issue_from_llm_response(llm_response_updated)
#
# if issue_details:
#     github_token = "YOUR_GITHUB_TOKEN_HERE"
#     repo_owner = "YOUR_REPO_OWNER"
#     repo_name = "YOUR_REPO_NAME"
#
#     try:
#         # Use the parsed issue details to create a GitHub issue
#         issue_url = create_github_issue(github_token, repo_owner, repo_name, issue_details)
#         print(f"Issue created successfully: {issue_url}")
#         # Here you can proceed to share the issue URL back via Slack
#     except Exception as e:
#         print(str(e))
#         # Handle the error appropriately (e.g., send a failure message back to Slack)
# else:
#     print("Issue details could not be parsed. Unable to create GitHub issue.")

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
