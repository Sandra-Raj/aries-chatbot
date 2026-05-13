# main.py

from fastapi import FastAPI
from config import DB_CONFIG, AI_MODEL, COMPANY_API_LINK
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_ollama import ChatOllama
from langchain_community.utilities import SQLDatabase

template = """
You are a Business Intelligence Analyst for Aries Marine. Based on the table schema below, 
translate questions into accurate MySQL queries.
Schema:
{schema}

STRICT BUSINESS LOGIC:
1. CLIENTS: Table '0_debtors_master' (alias m). Unique key is 'debtor_no'.
2. GEOGRAPHY/ORG: 
   - Country: 'dimension_id' -> Join '0_country' (id).
   - Division: 'dimension2_id' -> Join '0_dimensions' (id). Marine IDs: (3, 225).
   - Subdivision: 'dimension3_id' -> Join '0_dimensions' (id).
3. CRITICAL CLIENTS: m.client_status = cs.id WHERE cs.category = 2.

4. INACTIVE CLIENTS (COMPLEX LOGIC): 
   A client is 'Inactive' for a specific division if:
   - Their latest enquiry is older than 6 months.
   To find the latest enquiry, you MUST use this subquery pattern:
   LEFT JOIN (
       SELECT debtor_no, dimension2_id, MAX(enquiry_date) as last_date 
       FROM 0_client_enquiry 
       GROUP BY debtor_no, dimension2_id
   ) ce ON m.debtor_no = ce.debtor_no
   WHERE ce.last_date < DATE_SUB(CURDATE(), INTERVAL 6 MONTH) OR m.status = 0.

5. REVENUE: 
   SELECT SUM(a.alloc_amount * a.rate) 
   FROM 0_cust_allocations a 
   JOIN 0_debtor_trans t ON a.trans_no_to = t.trans_no 
   WHERE a.trans_type_from = 12.

6. IDLE CLIENTS: 
   A client is IDLE for Division X if they have records in '0_client_activity_status' for other divisions, but NO record where division = X.

QUERY RULES:
- Always use DATE_SUB(CURDATE(), INTERVAL X MONTH) for time-based queries.
- Use '0_debtors_master' as the base table for client lists.
- If the user asks for 'names', select m.name or m.debtor_ref.

Question: {question}
SQL Query:
"""

prompt = ChatPromptTemplate.from_template(template)


app = FastAPI()
connection_uri = (
    f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['pass']}"
    f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['db_name']}"
)

db = SQLDatabase.from_uri(connection_uri)

def get_schema(_):
    return db.get_table_info()

# print(get_schema(None))

def clean_sql_output(text: str):
    # Removes markdown backticks and 'sql' labels that Ollama often adds
    return text.replace("```sql", "").replace("```", "").strip()

llm = ChatOllama(
    model=AI_MODEL,
    base_url=COMPANY_API_LINK,
    temperature=0
)

sql_chain = (
    RunnablePassthrough.assign(schema=get_schema)
    | prompt
    | llm
    | StrOutputParser()
    | clean_sql_output
)

# sql_chain.invoke({"question": "How many clients in the database"})

template = """
    Based on the table schema below, question, sql query, and sql result, write a natural language result: 
    {schema}

    Question: {question}
    SQL Query: {query}
    SQL Result: {result}
"""

prompt = ChatPromptTemplate.from_template(template)

# This is the "Engine" that runs it all
def execute_full_chain(user_question: str):
    # Step A: Generate the SQL
    query = sql_chain.invoke({"question": user_question})
    
    # Clean up the query (local models often add backticks)
    query = query.replace("```sql", "").replace("```", "").strip()
    
    print(f"--- DEBUG: Generated SQL ---\n{query}\n---------------------------")
    
    # Step B: Run the SQL against the database
    try:
        db_result = db.run(query)
    except Exception as e:
        db_result = f"Error executing SQL: {str(e)}"
    # Step C: Turn result into a sentence
    final_result = prompt.pipe(llm).pipe(StrOutputParser()).invoke({
        "schema": get_schema,
        "question": user_question,
        "query": query,
        "result": db_result
    })
    
    return final_result

# 5. Testing the implementation
if __name__ == "__main__":
    test_question = "How many total clients are in the database?"
    result = execute_full_chain(test_question)
    print(f"FINAL ANSWER: {result}")

# def run_query(query):
#     return db.run(query)

# full_chain = (
#     RunnablePassthrough.assign(query=sql_chain).assign(
#         schema=get_schema,
#         result=lambda variables: run_query(variables["query"])
#     )
#     | prompt
#     | llm
#     | StrOutputParser()
# )

# input = "How many total clients are in the database?"

# full_chain.invoke({'question': input})



# from fastapi import FastAPI
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import SQLDatabaseToolkit
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
# from config import DB_CONFIG, AI_MODEL

# app = FastAPI()

# # Format: mysql+mysqlconnector://user:password@host:port/database
# connection_uri = (
#     f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['pass']}"
#     f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['db_name']}"
# )

# # Only list the tables the chatbot actually needs
# allowed_tables = ["0_client_activity_status", "0_client_credit_period", "0_client_enquiry", "0_client_type", "0_cust_allocations",
#                    "0_dimensions", "0_debtor_trans", "0_debtors_master", "0_temp_clients", "0_sales_orders", "0_client_status"]

# db = SQLDatabase.from_uri(
#     connection_uri, 
#     include_tables=allowed_tables, 
#     sample_rows_in_table_info=2)

# llm = ChatOllama(model=AI_MODEL, temperature=0) # Temperature 0 = factual/no guessing

# toolkit = SQLDatabaseToolkit(db=db, llm=llm)

# SQL_PREFIX = """
# You are a Business Intelligence Analyst for Aries Marine. 
# Your goal is to translate questions into accurate MySQL queries using the schema provided.

# STRICT BUSINESS LOGIC:
# 1. CLIENTS: Table '0_debtors_master' (alias m). Unique key is 'debtor_no'.
# 2. GEOGRAPHY/ORG: 
#    - Country: 'dimension_id' -> Join '0_country' (id).
#    - Division: 'dimension2_id' -> Join '0_dimensions' (id). Marine IDs: (3, 225).
#    - Subdivision: 'dimension3_id' -> Join '0_dimensions' (id).
# 3. CRITICAL CLIENTS: m.client_status = cs.id WHERE cs.category = 2.

# 4. INACTIVE CLIENTS (COMPLEX LOGIC): 
#    A client is 'Inactive' for a specific division if:
#    - Their latest enquiry is older than 6 months.
#    To find the latest enquiry, you MUST use this subquery pattern:
#    LEFT JOIN (
#        SELECT debtor_no, dimension2_id, MAX(enquiry_date) as last_date 
#        FROM 0_client_enquiry 
#        GROUP BY debtor_no, dimension2_id
#    ) ce ON m.debtor_no = ce.debtor_no
#    WHERE ce.last_date < DATE_SUB(CURDATE(), INTERVAL 6 MONTH) OR m.status = 0.

# 5. REVENUE: 
#    SELECT SUM(a.alloc_amount * a.rate) 
#    FROM 0_cust_allocations a 
#    JOIN 0_debtor_trans t ON a.trans_no_to = t.trans_no 
#    WHERE a.trans_type_from = 12.

# 6. IDLE CLIENTS: 
#    A client is IDLE for Division X if they have records in '0_client_activity_status' for other divisions, but NO record where division = X.

# QUERY RULES:
# - Always use DATE_SUB(CURDATE(), INTERVAL X MONTH) for time-based queries.
# - Use '0_debtors_master' as the base table for client lists.
# - If the user asks for 'names', select m.name or m.debtor_ref.
# """

# table_names = db.get_usable_table_names()
# formatted_prefix = SQL_PREFIX.format(table_names=table_names)

# # Define a suffix that includes the mandatory {agent_scratchpad}
# CUSTOM_SUFFIX = """
# Begin! 

# Question: {input}
# Thought: I should look at the tables in the database to see what I can query.
# {agent_scratchpad}"""

# agent_executor = create_sql_agent(
#     llm=llm,
#     toolkit=toolkit,
#     prefix=formatted_prefix,      # Your business rules go here
#     suffix=CUSTOM_SUFFIX,         # The 'thinking' part goes here
#     verbose=True,
#     agent_type="zero-shot-react-description", # Better for smaller local models
#     handle_parsing_errors=True
# )

# @app.get("/")
# def home():
#     # Test if the bot can see your tables
#     tables = db.get_usable_table_names()
#     return {"status": "Connected", "tables_found": tables}

# def ask_ai(question: str):
#     try:
#         result = agent_executor.invoke({"input": question})
#         return result["output"]
#     except Exception as e:
#         return f"Error: {str(e)}"

# result = agent_executor.invoke({"input": "How many clients are in the database?"})
# print(result["output"])

# # if __name__ == "__main__":
# #     # Test 1: Simple count
# #     print("Testing AI...")
# #     ans = ask_ai("How many total clients are in the database?")
# #     print(f"AI Answer: {ans}")
    
# #     # Test 2: Specific business query from your list
# #     ans = ask_ai("List the names of inactive clients in division 225.")
# #     print(f"AI Answer: {ans}")

