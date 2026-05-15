
# =========================================================
# ROUTING LOGIC (Context Aware)
# =========================================================
# INTENT_TEMPLATE = """You are a technical router for Aries Marine. Based on history and question, output a JSON object to call the correct function.

# Chat history: {history}

# FUNCTIONS:
# 1. get_client_enquiries(enq_type, enq_status) - Use for ANY question about enquiries, status or type.
#     - enq_type: 'Project', 'Annual Contract', 'Shutdown', 'Callout', 'Tender', or 'None'
#     - enq_status: 'Open', 'Cancel', 'Lost', 'Transfer', 'Confirmed', 'BID Enquiry', or 'None'

# IMPORTANT:
# - Output ONLY valid JSON.
# - NEVER add extra keys like "type", or "status_open" to the arguments.

# For example:

# User Question: "give all open client enquiries under division I&M in the last 3 months"
# Response:
#     {{
#         "function": "get_client_enquiries",
#         "arguments": {{
#             "enq_status": "Open"
#         }}
#     }}
# User Question: {question}
# Response:
# """

# =========================================================
# UTILITIES
# =========================================================
# def choose_function(user_query, chat_history):
#     history_str = "\n".join([f"{m.type}: {m.content}" for m in chat_history[-3:]])
    
#     prompt = ChatPromptTemplate.from_template(INTENT_TEMPLATE)
#     chain = prompt | llm | StrOutputParser()
    
#     response = chain.invoke({"question": user_query, "history": history_str})
#     print(f"DEBUG - Raw AI: {response}")

#     try:
#         # Step 1: If the model repeated the prompt examples, isolate the text after "Response:"
#         target_text = response
#         if "Response:" in response:
#             target_text = response.split("Response:")[-1]

#         # Step 2: Use greedy matching (.* instead of .*?) to capture the FULL JSON block.
#         # This ensures that internal braces like in "arguments": {} do not truncate the string.
#         match = re.search(r'(\{.*\})', target_text, re.DOTALL)
        
#         if not match:
#             return {"function": None, "arguments": {}}
        
#         json_str = match.group(1)
        
#         # Step 3: Clean potential comments or markdown leftovers
#         json_str = re.sub(r'//.*', '', json_str)
#         json_str = json_str.replace("```json", "").replace("```", "").strip()
        
#         # Step 4: Fix potential trailing commas before closing braces/brackets
#         json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
        
#         parsed = json.loads(json_str)
        
#         # Safety check for required keys
#         if "function" not in parsed:
#             return {"function": None, "arguments": {}}
#         if "arguments" not in parsed:
#             parsed["arguments"] = {}
#         return parsed
            
#     except Exception as e:
#         print(f"Router Error during parsing: {e}")
#     return {"function": None, "arguments": {}}
