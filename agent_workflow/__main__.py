
import shutil

from codex import Codex, ThreadStartOptions
from langchain.chat_models import init_chat_model
from langgraph.graph import MessagesState, StateGraph, START, END
from langchain_core.messages import AIMessage, get_buffer_string
from langgraph.checkpoint.memory import InMemorySaver
import uuid

import argparse
import os
import sys
from pathlib import Path


llm = Codex()

def prompt_llm(state: MessagesState):
    prompt = get_buffer_string(state["messages"])
    response = llm.run_text(prompt)
    return {"messages": [AIMessage(content=response)]}

def main():
    
    summary = llm.run_text("Diagnose the failing tests and propose a fix")
    print("Starting agent workflow...")

    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node(prompt_llm)
    graph_builder.add_edge(START, 'prompt_llm')
    graph_builder.add_edge('prompt_llm', END)

    checkpointer = InMemorySaver()
    graph = graph_builder.compile(checkpointer=checkpointer)

    config = {'configurable':{'thread_id': uuid.uuid4()}}
    while True:
        user_message = input('Enter message:')
        print(graph.invoke({'messages':[{'role':'user','content':user_message}]}, config=config))

if __name__ == "__main__":
    main()
