from langchain_ollama import ChatOllama



# Connect to your local Llama 3.1
llm = ChatOllama(model="llama3.1")

response = llm.invoke("Hello! Are you ready to analyze my MySQL data?")
print(response.content)