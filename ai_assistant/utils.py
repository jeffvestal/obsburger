import requests
import json
from datetime import datetime, timedelta


def _get_genai_connector_id(
    kibana_url,
    auth,
    model,
):
    """Obtains the GenAI connector id from the Kibana API. Prints error if no available connector id is found.

    Args:
      (str) kibana_url: URL to Kibana instance
      ((str, str)) auth: tuple (username, password) to access Kibana
      (str) model: LLM model to use, options: .gen-ai (OpenAI or Azure OpenAI) or .bedrock

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
    try:
        connectors = requests.get(
            url=url_connector, headers=headers, auth=auth, verify=True
        )
    except Exception as e:
        print("Connection Error with Kibana - Make sure it's running")
        raise e

    if connectors.status_code == 404:
        raise Exception("ERROR - Wrong Kibana url or credentials")
    elif connectors.status_code == 401:
        raise Exception("ERROR - Unauthorized -  unable to authenticate user")

    connectors_ai = [
        conn for conn in connectors.json() if conn["connector_type_id"] == model
    ]
    # print('connectors_ai:', connectors_ai)
    # print()
    if len(connectors_ai) == 0:
        raise Exception(
            f"ERROR - No GenAI connectors found for {model}, please add your GenAI connector to Kibana"
        )
    # return connectors_ai[0]["id"]
    return 'ce4b2de5-d9f0-4793-bee6-169749c0d51b' # azure-pmm-westus


def _get_kibana_version(kibana_url, auth):
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


def _get_assistants_system_prompt(kibana_url, auth):
    """Obtains the Assistant's system prompt fron the Assistants API

    Args:
      (str) kibana_url: URL to Kibana instance
      ((str, str)) auth: tuple (username, password) to access Kibana

    Returns:
      (str) System prompt
    """

    headers = {
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    url = f"{kibana_url}/internal/observability_ai_assistant/functions"
    functions = requests.get(url=url, headers=headers, auth=auth, verify=True)
    system_prompt = [
        f for f in functions.json()["contextDefinitions"] if f["name"] == "core"
    ][0]["description"]
    return system_prompt


def _get_assistants_response(
    headers,
    data,
    streaming,
    print_streaming_response,
    kibana_url,
    auth,
):
    """Handles response from the Assistant in streaming or non-streaming mode

    Args:
      (str) kibana_url: URL to Kibana instance
      ((str, str)) auth: tuple (username, password) to access Kibana
      (dict) headers
      (dict) data
      (boolean) streaming to stream the responses, or False to wait for the entire response, allows to show intermediate responses like function calls
      (boolean) print_streaming_response to print the message response of the assistant in streaming, or false to print the message response at the end
    Returns:
      (list) List of the json responses from the API
    """

    url = f"{kibana_url}/internal/observability_ai_assistant/chat/complete"
    if streaming == False:
        response = requests.post(
            url=url, headers=headers, auth=auth, verify=True, data=data
        )
        response_array = [json.loads(i) for i in response.text.split("\n") if i != ""]
    else:
        response_array = []
        initchatCompletionChunk = True
        with requests.post(
            url=url, headers=headers, auth=auth, verify=True, data=data, stream=True
        ) as response:
            try:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line and line != "":  # Ignore keep-alive new lines
                            response_json = json.loads(line.decode("utf-8"))
                            response_array.append(response_json)
                            if response_json != None:
                                if (
                                    response_json.get("type") == "chatCompletionChunk"
                                    and print_streaming_response
                                    and response_json.get("message").get("content")
                                    # != ""
                                    not in (None, "")
                                ):
                                    if initchatCompletionChunk:
                                        print(
                                            "\x1b[6;30;46m" + "Assistant:" + "\x1b[0m",
                                            end=" ",
                                        )
                                        initchatCompletionChunk = False
                                    print(
                                        response_json.get("message").get("content"),
                                        end="",
                                        flush=True,
                                    )
                                    initchatCompletionChunk = False
                                if response_json.get("type") == "messageAdd":
                                    if (
                                        response_json.get("message")
                                        .get("message")
                                        .get("role")
                                        == "assistant"
                                        and response_json.get("message")
                                        .get("message")
                                        .get("content")
                                        != "[]"
                                    ):
                                        content = (
                                            response_json.get("message")
                                            .get("message")
                                            .get("content")
                                        )
                                        if content == "":
                                            functions = (
                                                response_json.get("message")
                                                .get("message")
                                                .get("function_call")
                                                .get("name")
                                            )
                                            print(
                                                "\x1b[6;30;46m"
                                                + "Assistant executing functions:"
                                                + "\x1b[0m"
                                                + f" {functions}"
                                            )
                else:
                    print(f"ERROR: Response status code {response.status_code}")
            except Exception as e:
                print(f"ERROR: {str(e)}")
    return response_array


def ask_assistant(
    kibana_url,
    auth,
    model,
    user_question,
    conversation={},
    persist_conversation=False,
    streaming=False,
    print_streaming_response=False,
):
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
    connector_id = _get_genai_connector_id(kibana_url, auth, model)

    headers = {
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    data = {
        "messages": [],
        "connectorId": connector_id,
        "persist": persist_conversation,
    }

    if persist_conversation and conversation != {}:
        data["conversationId"] = conversation["conversationId"]

    version = _get_kibana_version(kibana_url, auth)
    if int(version.split(".")[0]) >= 8 and int(version.split(".")[1]) >= 13:
        data["screenContexts"] = []
        assistant_sytem_message = _get_assistants_system_prompt(kibana_url, auth)
    else:
        assistant_sytem_message = 'You are a helpful assistant for Elastic Observability. Your goal is to help the Elastic Observability users to quickly assess what is happening in their observed systems. You can help them visualise and analyze data, investigate their systems, perform root cause analysis or identify optimisation opportunities.\\n\\nIt\'s very important to not assume what the user is meaning. Ask them for clarification if needed.\\n\\nIf you are unsure about which function should be used and with what arguments, ask the user for clarification or confirmation.\\n\\nIn KQL, escaping happens with double quotes, not single quotes. Some characters that need escaping are: \':()\\\\        /\\". Always put a field value in double quotes. Best: service.name:\\"opbeans-go\\". Wrong: service.name:opbeans-go. This is very important\u0021\\n\\nYou can use Github-flavored Markdown in your responses. If a function returns an array, consider using a Markdown table to format the response.\\n\\nIf multiple functions are suitable, use the most specific and easy one. E.g., when the user asks to visualise APM data, use the APM functions (if available) rather than Lens.\\n\\nIf a function call fails, DO NOT UNDER ANY CIRCUMSTANCES execute it again. Ask the user for guidance and offer them options.\\n\\nNote that ES|QL (the Elasticsearch query language, which is NOT Elasticsearch SQL, but a new piped language) is the preferred query language.\\n\\nUse the \\"get_dataset_info\\" function if it is not clear what fields or indices the user means, or if you want to get more information about the mappings.\\n\\nIf the user asks about a query, or ES|QL, always call the \\"esql\\" function. DO NOT UNDER ANY CIRCUMSTANCES generate ES|QL queries or explain anything about the ES|QL query language yourself.\\nEven if the \\"recall\\" function was used before that, follow it up with the \\"esql\\" function. If a query fails, do not attempt to correct it yourself. Again you should call the \\"esql\\" function,\\neven if it has been called before.\\n\\nIf the \\"get_dataset_info\\" function returns no data, and the user asks for a query, generate a query anyway with the \\"esql\\" function, but be explicit about it potentially being incorrect.You can use the \\"summarize\\" functions to store new information you have learned in a knowledge database. Once you have established that you did not know the answer to a question, and the user gave you this information, it\'s important that you create a summarisation of what you have learned and store it in the knowledge database. Don\'t create a new summarization if you see a similar summarization in the conversation, instead, update the existing one by re-using its ID.\\n\\nAdditionally, you can use the \\"recall\\" function to retrieve relevant information from the knowledge database."}}'

    if conversation == {}:
        system_message = {
            "@timestamp": (datetime.now() - timedelta(minutes=2)).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            ),
            "message": {
                "role": "system",
                "content": assistant_sytem_message,
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

    response_array = _get_assistants_response(
        headers, data, streaming, print_streaming_response, kibana_url, auth
    )

    messages = [r["message"] for r in response_array if r["type"] == "messageAdd"]
    if persist_conversation and conversation == {}:
        conversationId = [
            r for r in response_array if r["type"] == "conversationCreate"
        ][0]["conversation"]["id"]
    elif persist_conversation == False:
        conversationId = None
    else:
        conversationId = conversation["conversationId"]

    if conversation == {}:
        messages = [system_message, user_message] + messages
    else:
        messages = conversation["messages"] + [user_message] + messages

    if persist_conversation == False:
        message_index = -1
    else:
        message_index = -2

    try:
        assistant_response = response_array[message_index]["message"]["message"][
            "content"
        ]
        if not print_streaming_response or not streaming:
            print("\x1b[6;30;46m" + "Assistant:" + "\x1b[0m" + f" {assistant_response}")
        return {
            "conversationId": conversationId,
            "response": assistant_response,
            "messages": messages,
        }
    except:
        print(f"Response was not successful: {response_array}")
        print(f"ERROR - API Response was not successful -----")
        return {
            "conversationId": "ERROR",
            "response": "ERROR" + str(response_array[0]),
            "messages": [],
        }