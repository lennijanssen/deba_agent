from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from google.cloud import firestore
from langchain_google_firestore import FirestoreChatMessageHistory

from deba_timetable_tool import db_departures


# ---------------- Firestore config ----------------
PROJECT_ID = "debaagent-e2d1c"
SESSION_ID = "timetabletesting"            # keep it stable per user/session
COLLECTION_NAME = "conversation_history"   # your Firestore collection

print("Initializing Firestore Client")
client = firestore.Client(project=PROJECT_ID)

print("Initializing Chat Message History")
chat_history = FirestoreChatMessageHistory(
    session_id=SESSION_ID,
    collection=COLLECTION_NAME,
    client=client,
)

# ---------------- Seed system prompt once ----------------
if not chat_history.messages:
    chat_history.add_message(SystemMessage(
        content=(
            "You are a concise assistant.\n"
            "When calling tools:\n"
            "- Only include 'date_iso' and 'hour_24' if the USER explicitly provided them.\n"
            "- Otherwise, leave them NULL/omitted so the tool will default to the current date and hour.\n"
            "- Never guess or invent dates or times."
        )
    ))

# ---------------- LLM + Tools Agent ----------------
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tools = [db_departures]

prompt = ChatPromptTemplate.from_messages([
    MessagesPlaceholder(variable_name="chat_history"),  # inject Firestore history
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_openai_tools_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)


# ---------------- Helper: robust reply extraction ----------------
def extract_agent_reply(result: dict) -> str:
    """
    Extract a clean, human-readable reply from an AgentExecutor result.
    Prefers 'output'; falls back to last tool observation from 'intermediate_steps';
    finally falls back to '(no textual output)' instead of dumping the whole dict.
    """
    if not isinstance(result, dict):
        return str(result)

    # 1) Normal path
    out = result.get("output")
    if isinstance(out, str) and out.strip():
        return out

    # 2) Some configs: return_values
    rv = result.get("return_values") or {}
    out = rv.get("output") or rv.get("answer")
    if isinstance(out, str) and out.strip():
        return out

    # 3) Tools agent: last observation often holds the answer text
    steps = result.get("intermediate_steps")
    if isinstance(steps, list) and steps:
        try:
            observation = steps[-1][1]
            if isinstance(observation, str) and observation.strip():
                return observation
        except Exception:
            pass

    # 4) Messages fallback
    msgs = result.get("messages")
    if isinstance(msgs, list) and msgs:
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, str) and content.strip():
            return content

    # 5) Final: avoid dumping dict baggage
    return "x"


# ---------------- Chat loop ----------------
print("Your Turn (or 'exit'):")
while True:
    try:
        user_query = input("> ").strip()
        if not user_query:
            continue
        if user_query.lower() in {"exit", "quit"}:
            print("bye!")
            break

        # Store user message
        chat_history.add_message(HumanMessage(content=user_query))

        # Invoke agent with history
        result = agent_executor.invoke({
            "input": user_query,
            "chat_history": chat_history.messages,  # pass history
        })

        # Extract and persist assistant reply safely
        reply = extract_agent_reply(result)
        chat_history.add_message(AIMessage(content=reply))
        print(reply, end="\n\n")

    except (KeyboardInterrupt, EOFError):
        print("\nbye!")
        break
