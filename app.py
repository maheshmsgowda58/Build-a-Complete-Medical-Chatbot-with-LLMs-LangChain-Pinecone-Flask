from flask import Flask, render_template, request, session
from src.helper import download_hugging_face_embeddings
from langchain_pinecone import PineconeVectorStore
from langchain_groq import ChatGroq
from langchain.chains.retrieval import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from src.prompt import *
from langgraph.store.memory import InMemoryStore
import os
import uuid

# -------------------- Flask Setup --------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Needed for session
load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY
os.environ["GROQ_API_KEY"] = GROQ_API_KEY

# -------------------- Memory Store --------------------
memory_store = InMemoryStore()

# -------------------- Embeddings & Retriever --------------------
embeddings = download_hugging_face_embeddings()
index_name = "medical-chatbot"

docsearch = PineconeVectorStore.from_existing_index(
    index_name=index_name,
    embedding=embeddings
)

retriever = docsearch.as_retriever(search_type="similarity", search_kwargs={"k": 3})

# -------------------- Chat Model & RAG Chain --------------------
chatModel = ChatGroq(model_name="llama-3.3-70b-versatile")

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        ("human", "{input}"),
    ]
)

question_answer_chain = create_stuff_documents_chain(chatModel, prompt)
rag_chain = create_retrieval_chain(retriever, question_answer_chain)

# -------------------- Routes --------------------
@app.route("/")
def index():
    # Reset session memory on page load
    session.clear()
    return render_template('chat.html')


@app.route("/get", methods=["GET", "POST"])
def chat():
    msg = request.form["msg"]

    # Use session id for per-user memory
    user_id = session.get("user_id")
    if not user_id:
        user_id = str(uuid.uuid4())
        session["user_id"] = user_id

    namespace = (user_id, "memories")

    # Store user input
    memory_id = str(uuid.uuid4())
    memory_store.put(namespace, memory_id, {"role": "user", "content": msg})

    # Retrieve previous memories for this session
    previous_memories = memory_store.search(namespace, query=msg, limit=5)
    context_text = " ".join([m.value.get("content", "") for m in previous_memories])
    input_with_context = f"{context_text} {msg}" if context_text else msg

    # Generate response
    response = rag_chain.invoke({"input": input_with_context})

    # Store assistant response
    memory_id = str(uuid.uuid4())
    memory_store.put(namespace, memory_id, {"role": "assistant", "content": response["answer"]})

    return str(response["answer"])


# -------------------- Run Flask --------------------
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080, debug=True)
