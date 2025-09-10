import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from google.cloud import firestore
from langchain_google_firestore import FirestoreChatMessageHistory

from deba_timetable_tool import db_departures

# ---------------- config ----------------
PROJECT_ID = os.getenv("PROJECT_ID", "debaagent-e2d1c")
COLLECTION_NAME = "conversation_history"
app = FastAPI(title="Deba Agent API")

# ---------------- Firestore ----------------
_fs_client = None
def get_fs_client():
    global _fs_client
    if _fs_client is None:
        _fs_client = firestore.Client(project=PROJECT_ID)
    return _fs_client

def get_chat_history(session_id: str):
    client = get_fs_client()
    chat_history = FirestoreChatMessageHistory(
        session_id=session_id,
        collection=COLLECTION_NAME,
        client=client,
    )
    if not chat_history.messages:
        chat_history.add_message(SystemMessage(
            content=(
                "You are a concise assistant.\n"
                "When calling tools:\n"
                "- Only include 'date_iso' and 'hour_24' if the USER explicitly provided them.\n"
                "- Otherwise, leave them NULL/omitted so the tool defaults to now.\n"
                "- Never guess or invent dates/times.\n"
                "You ALWAYS produce a final, plain-text answer after any tool calls."
            )
        ))
    return chat_history

# ---------------- Agent setup ----------------
tools = [db_departures]
prompt = ChatPromptTemplate.from_messages([
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

def build_agent_executor():
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=openai_key)
    agent = create_openai_tools_agent(llm, tools, prompt)

    # return intermediate steps so we can fall back to tool output if model doesn't speak
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        return_intermediate_steps=True,
        handle_parsing_errors=True,
    )

# ---------------- Reply extraction ----------------
def extract_agent_reply(result: dict) -> str:
    # 1) normal path
    out = (result.get("output") or "").strip()
    if out:
        return out

    # 2) fallback: last tool observation
    steps = result.get("intermediate_steps") or []
    if steps:
        try:
            observation = steps[-1][1]
            if isinstance(observation, str) and observation.strip():
                return observation.strip()
        except Exception:
            pass
    # 3) last message content
    msgs = result.get("messages") or []
    if msgs:
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return "(no answer generated)"

# ---------------- FastAPI - models & endpoints ----------------
class ChatRequest(BaseModel):
    session_id: str
    text: str

class ChatResponse(BaseModel):
    reply: str

@app.get("/")
def root():
    return {"service": "debaagent", "endpoints": ["/healthz", "/chat", "/docs"]}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/chat", response_model=ChatResponse)
def chat(q: ChatRequest):
    try:
        history = get_chat_history(q.session_id)
        executor = build_agent_executor()
        history.add_message(HumanMessage(content=q.text))
        result = executor.invoke({"input": q.text, "chat_history": history.messages})
        reply = extract_agent_reply(result).strip() or "..."
        history.add_message(AIMessage(content=reply))
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
