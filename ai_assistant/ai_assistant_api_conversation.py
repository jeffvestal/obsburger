import os
from utils import ask_assistant

# Replace with your Kibana URL and credentials
KIBANA_URL = os.getenv("KIBANA_URL", "http://localhost:5601/")
KIBANA_USERNAME = os.getenv("KIBANA_USERNAME", "xx")
KIBANA_PASSWORD = os.getenv("KIBANA_PASSWORD", "xx")
AUTH = (KIBANA_USERNAME, KIBANA_PASSWORD)
MODEL = ".gen-ai"  # can be changed to '.bedrock'
PERSIST_CONVERSATION = True  # Save conversation in AI Assistan's UI
STREAMING = True  # to stream the responses, allows to show intermediate responses like function calls, or False to wait for the entire response and only show final message
PRINT_STREAMING_RESPONSE = True  # to print the message response of the assistant in streaming, or False to wait for the entire message response to print it

new_conversation = True
user_message = ""

while True:
    if user_message == "new conversation" or new_conversation:
        user_message = input(
            "\x1b[6;30;42m" + "How can I help today?" + "\x1b[0m" + " "
        )
        response = ask_assistant(
            kibana_url=KIBANA_URL,
            auth=AUTH,
            model=MODEL,
            user_question=user_message,
            persist_conversation=PERSIST_CONVERSATION,
            streaming=STREAMING,
            print_streaming_response=PRINT_STREAMING_RESPONSE,
        )
        new_conversation = False
    else:
        user_message = input("\n" + "\x1b[6;30;44m" + "You:" + "\x1b[0m" + " ")
        if user_message == "quit":
            break
        elif user_message != "new conversation":
            response = ask_assistant(
                kibana_url=KIBANA_URL,
                auth=AUTH,
                model=MODEL,
                user_question=user_message,
                conversation={
                    "conversationId": response["conversationId"],
                    "messages": response["messages"],
                },
                persist_conversation=PERSIST_CONVERSATION,
                streaming=STREAMING,
                print_streaming_response=PRINT_STREAMING_RESPONSE,
            )