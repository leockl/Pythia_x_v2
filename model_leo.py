import os
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor
from llm_guard import scan_output, scan_prompt
from llm_guard.input_scanners import Anonymize, PromptInjection, TokenLimit, Toxicity
from llm_guard.output_scanners import Deanonymize, NoRefusal, Relevance, Sensitive
from llm_guard.vault import Vault

boto3_session = boto3.session.Session()
region = boto3_session.region_name

# create a boto3 bedrock client
bedrock_agent_runtime_client = boto3.client('bedrock-agent-runtime')

# get knowledge base id from environment variable
kb_id = os.environ.get("KNOWLEDGE_BASE_ID")

# declare model id for calling RetrieveAndGenerate API
model_id = "mistral.mixtral-8x7b-instruct-v0:1"
model_arn = f'arn:aws:bedrock:{region}::foundation-model/{model_id}'

def retrieveAndGenerate(input, kbId, model_arn, sessionId=None):
    # print(input, kbId, model_arn)
    if sessionId != "None":
        return bedrock_agent_runtime_client.retrieve_and_generate(
            input={
                'text': input
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kbId,
                    'modelArn': model_arn
                }
            },
            sessionId=sessionId
        )
    else:
        return bedrock_agent_runtime_client.retrieve_and_generate(
            input={
                'text': input
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kbId,
                    'modelArn': model_arn
                }
            }
        )

SCHEMA = '''
CREATE TABLE trades (
exchange character varying(20),
symbol character varying(20),
price double precision,
size double precision,
taker_side character varying(5),
trade_id character varying(64),
event_timestamp timestamp without time zone,
atom_timestamp bigint
);

CREATE TABLE trades_l3 (
    exchange character varying(20),
    symbol character varying(20),
    price double precision,
    size double precision,
    taker_side character varying(5),
    trade_id character varying(64),
    maker_order_id character varying(64),
    taker_order_id character varying(64),
    event_timestamp timestamp without time zone,
    atom_timestamp bigint
);

CREATE TABLE candle (
    exchange character varying(20),
    symbol character varying(20),
    start timestamp without time zone,
    "end" timestamp without time zone,
    "interval" character varying(10),
    trades integer,
    closed boolean,
    o double precision,
    h double precision,
    l double precision,
    c double precision,
    v double precision,
    event_timestamp timestamp without time zone,
    atom_timestamp bigint
);

CREATE TABLE ethereum_blocks (
    blocktimestamp timestamp without time zone,
    atomtimestamp bigint,
    number integer,
    hash character(66) NOT NULL,
    parenthash character(66),
    nonce character(18),
    sha3uncles character(66),
    logsbloom character(514),
    transactionsroot character(66),
    stateroot character(66),
    receiptsroot character(66),
    miner character(42),
    difficulty bigint,
    totaldifficulty numeric,
    extradata text,
    size bigint,
    gaslimit numeric,
    gasused numeric
);

CREATE TABLE ethereum_logs (
    atomtimestamp bigint,
    blocktimestamp timestamp without time zone NOT NULL,
    logindex integer NOT NULL,
    transactionindex integer,
    transactionhash character(66) NOT NULL,
    blockhash character(66),
    blocknumber bigint,
    address character(42),
    data text,
    topic0 text,
    topic1 text,
    topic2 text,
    topic3 text
)

CREATE TABLE ethereum_transactions (
    blocktimestamp timestamp without time zone NOT NULL,
    atomtimestamp bigint,
    blocknumber integer,
    blockhash character(66),
    hash character(66) NOT NULL,
    nonce text,
    transactionindex integer,
    fromaddr character(42),
    toaddr character(42),
    value numeric,
    gas bigint,
    gasprice bigint,
    input text,
    maxfeepergas bigint,
    maxpriorityfeepergas bigint,
    type text
)

CREATE TABLE ethereum_token_transfers (
    atomtimestamp bigint,
    blocktimestamp timestamp without time zone NOT NULL,
    tokenaddr character(42),
    fromaddr text,
    toaddr text,
    value numeric,
    transactionhash character(66) NOT NULL,
    logindex integer NOT NULL,
    blocknumber bigint,
    blockhash character(66)
)
'''

# Database connection parameters
db_params = {
    'dbname': 'postgres',
    'user': 'viewer_account',
    'password': 'Zt8O0R8i4W7cEbTXFi80SZswUXPpQann',
    'host': '136.144.62.142',
    'port': '5432'
}

# Execute sql query in postgres database
def execute_query(query):
    """Executes a SQL query and returns the results."""
    conn = psycopg2.connect(**db_params)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(query)
        result = cursor.fetchall()
        conn.commit()
        return result
    except Exception as e:
        print(f"Database error: {e}")
        print(f"Failed SQL: {query}")  # Log the failed SQL query for debugging
        return None
    finally:
        cursor.close()
        conn.close()

sql_agent_system_content = f"""
Act as an expert programmer in SQL. You are an AI assistant that translates natural language into read-only SQL queries
based on the provided schema: {SCHEMA}

Guidelines:
1. Only output valid SQL queries, no other text or explanations.
2. Design queries suitable for charts used in a charting library called Recharts.
3. Trading pairs format: "BASE.QUOTE" (uppercase).
4. Use trades_l3 table for "binance" and "coinbase" exchanges, trades table for others.
5. Exchange names are lowercase.

Prioritize:
1. Accuracy and validity of the generated SQL query.
2. Optimal use of the provided schema and tables.
3. Relevance, conciseness and clarity of the query.
"""

def determine_chart_type(table_data):
    # Analyze the data types in the table
    data_types = set()
    for row in table_data:
        for value in row.values():
            data_types.add(type(value).__name__)

    # Determine the best chart type based on the data types
    if 'float' in data_types or 'int' in data_types:
        if 'datetime' in data_types:
            return 'LineChart'  # Line chart for time series data
        else:
            return 'BarChart'  # Bar chart for numeric data
    elif 'str' in data_types:
        return 'PieChart'  # Pie chart for categorical data
    else:
        return 'BarChart'  # Default to bar chart if data types are unclear
    
def generate_recharts_code(chart_type, table_data):
    # Generate Recharts code based on the chart type and table data
    if chart_type == 'LineChart':
        # Generate Recharts code for a line chart
        data_keys = list(table_data[0].keys())
        x_axis_datakey = data_keys[0]
        y_axis_datakeys = data_keys[1:]

        recharts_code = f"""
        <LineChart width={{800}} height={{400}} data={{data}}>
          <XAxis dataKey="{x_axis_datakey}" />
          <YAxis />
          <CartesianGrid strokeDasharray="3 3" />
          <Tooltip />
          <Legend />
          {' '.join([f'<Line type="monotone" dataKey="{key}" stroke="#8884d8" />' for key in y_axis_datakeys])}
        </LineChart>
        """

    elif chart_type == 'BarChart':
        # Generate Recharts code for a bar chart
        data_keys = list(table_data[0].keys())
        x_axis_datakey = data_keys[0]
        y_axis_datakeys = data_keys[1:]

        recharts_code = f"""
        <BarChart width={{800}} height={{400}} data={{data}}>
          <XAxis dataKey="{x_axis_datakey}" />
          <YAxis />
          <CartesianGrid strokeDasharray="3 3" />
          <Tooltip />
          <Legend />
          {' '.join([f'<Bar dataKey="{key}" fill="#8884d8" />' for key in y_axis_datakeys])}
        </BarChart>
        """

    elif chart_type == 'PieChart':
        # Generate Recharts code for a pie chart
        data_keys = list(table_data[0].keys())
        name_key = data_keys[0]
        value_key = data_keys[1]

        recharts_code = f"""
        <PieChart width={{800}} height={{400}}>
          <Pie
            data={{data}}
            dataKey="{value_key}"
            nameKey="{name_key}"
            cx="50%"
            cy="50%"
            outerRadius={{150}}
            fill="#8884d8"
            label
          />
          <Tooltip />
        </PieChart>
        """

    elif chart_type == 'ScatterChart':
        # Generate Recharts code for a scatter chart
        data_keys = list(table_data[0].keys())
        x_axis_datakey = data_keys[0]
        y_axis_datakey = data_keys[1]

        recharts_code = f"""
        <ScatterChart width={{800}} height={{400}}>
          <XAxis dataKey="{x_axis_datakey}" />
          <YAxis dataKey="{y_axis_datakey}" />
          <CartesianGrid strokeDasharray="3 3" />
          <Tooltip />
          <Scatter name="Data" data={{data}} fill="#8884d8" />
        </ScatterChart>
        """

    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")

    return recharts_code

# AI safety (LLM Guard) variables
vault = Vault()
input_scanners = [Anonymize(vault), Toxicity(), TokenLimit(), PromptInjection()]
output_scanners = [Deanonymize(vault), NoRefusal(), Relevance(), Sensitive()]

def lambda_handler(event, context):
    query = event["question"]
    session_id = event["sessionid"]

    # Sanitizing (AI safety) user query
    sanitized_query, results_valid, results_score = scan_prompt(input_scanners, query)
    
    question_and_answer_chat_history = """
    Act as an expert in crypto, blockchain and web3. 
    
    You are a helpful assistant who provide responses to user questions based on the context in crypto, blockchain and web3 only, 
    with the following 4 exceptions: 
    
    1. if the user asks to produce a table using the keyword &table (and does not ask to produce a chart using the keyword &chart) 
    based on data from Binance, Coinbase, dYdX, Bybit, OKX, Uniswap, Magic Eden and Ethereum network or chain from 1st Nov 2022 
    to 30th Apr 2024, then provide the response "agent1". 

    2. if the user asks to produce a chart using the keyword &chart (and does not ask to produce a table using the keyword &table) 
    based on data from Binance, Coinbase, dYdX, Bybit, OKX, Uniswap, Magic Eden and Ethereum network or chain from 1st Nov 2022 
    to 30th Apr 2024, then provide the response "agent2". 

    3. if the user asks to produce a table and a chart using the keyword &table and &chart based on data from Binance, Coinbase, 
    dYdX, Bybit, OKX, Uniswap, Magic Eden and Ethereum network or chain from 1st Nov 2022 to 30th Apr 2024, then provide the 
    response "agent3". 

    4. if the user asks a question based on data from Binance, Coinbase, dYdX, Bybit, OKX, Uniswap, Magic Eden and Ethereum network 
    or chain from 1st Nov 2022 to 30th Apr 2024, then provide the response "agent4".
    
    Do not provide responses to user questions which are unrelated to crypto, blockchain and web3 or user questions which are unrelated 
    to the 4 exceptions above.
    """

    question_and_answer_chat_history += f"\nUser: {sanitized_query}"
    
    # Get response from general q&a AI agent
    temporary_response = retrieveAndGenerate(question_and_answer_chat_history, kb_id, model_arn, session_id)['output']['text']

    # Sanitizing (AI safety) llm response
    sanitized_temporary_response, results_valid, results_score = scan_output(output_scanners, sanitized_query, temporary_response)
    
    if "agent1" in sanitized_temporary_response:
        # Get response from sql AI agent
        sql_code = retrieveAndGenerate(sql_agent_system_content + f"\nConvert this natural language question to SQL code: {sanitized_query}", kb_id, model_arn, session_id)['output']['text']
        
        sql_code = sql_code.strip()

        # Trim Markdown code block syntax accurately and ensure "sql" prefix is properly removed
        if sql_code.startswith("```sql"):
            sql_code = sql_code[6:]  # Remove starting "```sql"
        elif sql_code.startswith("sql"):
            sql_code = sql_code[3:]  # Remove starting "sql" if it's directly at the beginning

        sql_code = sql_code.strip(" `\n")  # Trim spaces, backticks, and newlines from both ends

        # Connect to sql db, fetch table as a list of dictionaries
        table_data = execute_query(sql_code)

        # Append table to question_and_answer_chat_history
        question_and_answer_chat_history += f"\nAssistant: {str(table_data)}"

        # Get response from summary AI agent
        summary = retrieveAndGenerate(f"convert list of dictionaries table to natural language summary: {table_data}", kb_id, model_arn, session_id)['output']['text']
        # question_and_answer_chat_history += f"\nAssistant: {summary}"

        # Display table and summary as response
        return {
            'statusCode': 200,
            # 'body': {"question": query.strip(), "answer": f"{table_data}\n{summary}"}
            'body': {"answer": f"{table_data}\n{summary}"}
        }
    elif "agent2" in sanitized_temporary_response:
        # Get response from sql AI agent
        sql_code = retrieveAndGenerate(sql_agent_system_content + f"\nConvert this natural language question to SQL code: {sanitized_query}", kb_id, model_arn, session_id)['output']['text']
        
        sql_code = sql_code.strip() # Trim whitespaces on both ends

        # Trim Markdown code block syntax accurately and ensure "sql" prefix is properly removed
        if sql_code.startswith("```sql"):
            sql_code = sql_code[6:]  # Remove starting "```sql"
        elif sql_code.startswith("sql"):
            sql_code = sql_code[3:]  # Remove starting "sql" if it's directly at the beginning

        sql_code = sql_code.strip(" `\n")  # Trim spaces, backticks, and newlines from both ends

        # Connect to sql db, fetch table as a list of dictionaries
        table_data = execute_query(sql_code)

        # Determine the best chart type based on the data types in the table
        chart_type = determine_chart_type(table_data)

        # Generate Recharts code based on chart type and data
        recharts_code = generate_recharts_code(chart_type, data)

        # Append table to question_and_answer_chat_history
        question_and_answer_chat_history += f"\nAssistant: {str(table_data)}"

        # Get response from summary AI agent
        summary = retrieveAndGenerate(f"convert list of dictionaries table to natural language summary: {table_data}", kb_id, model_arn, session_id)['output']['text']
        # question_and_answer_chat_history += f"\nAssistant: {summary}"

        # Display chart and summary as response
        return {
            'statusCode': 200,
            # 'body': {"question": query.strip(), "answer": f"[chart image]\n{summary}"}
            'body': {"answer": f"{recharts_code}\n{summary}"}
        }
    elif "agent3" in sanitized_temporary_response:
        # Get response from sql AI agent
        sql_code = retrieveAndGenerate(sql_agent_system_content + f"\nconvert natural language to sql code: {sanitized_query}", kb_id, model_arn, session_id)['output']['text']
        
        sql_code = sql_code.strip() # Trim whitespaces on both ends

        # Trim Markdown code block syntax accurately and ensure "sql" prefix is properly removed
        if sql_code.startswith("```sql"):
            sql_code = sql_code[6:]  # Remove starting "```sql"
        elif sql_code.startswith("sql"):
            sql_code = sql_code[3:]  # Remove starting "sql" if it's directly at the beginning

        sql_code = sql_code.strip(" `\n")  # Trim spaces, backticks, and newlines from both ends

        # Connect to sql db, fetch table as a list of dictionaries
        table_data = execute_query(sql_code)

        # Determine the best chart type based on the data types in the table
        chart_type = determine_chart_type(table_data)

        # Generate Recharts code based on chart type and data
        recharts_code = generate_recharts_code(chart_type, data)

        # Append table to question_and_answer_chat_history
        question_and_answer_chat_history += f"\nAssistant: {str(table_data)}"

        # Get response from summary AI agent
        summary = retrieveAndGenerate(f"convert list of dictionaries table to natural language summary: {table_data}", kb_id, model_arn, session_id)['output']['text']
        # question_and_answer_chat_history += f"\nAssistant: {summary}"

        # Display table, chart and summary as response
        return {
            'statusCode': 200,
            'body': {"answer": f"{table_data}\n{recharts_code}\n{summary}"}
        }
    elif "agent4" in sanitized_temporary_response:
        # Get response from sql AI agent
        sql_code = retrieveAndGenerate(sql_agent_system_content + f"convert natural language to sql code: {sanitized_query}", kb_id, model_arn, session_id)['output']['text']
        
        sql_code = sql_code.strip() # Trim whitespaces on both ends

        # Trim Markdown code block syntax accurately and ensure "sql" prefix is properly removed
        if sql_code.startswith("```sql"):
            sql_code = sql_code[6:]  # Remove starting "```sql"
        elif sql_code.startswith("sql"):
            sql_code = sql_code[3:]  # Remove starting "sql" if it's directly at the beginning

        sql_code = sql_code.strip(" `\n")  # Trim spaces, backticks, and newlines from both ends

        # Connect to sql db, fetch table as a list of dictionaries
        table_data = execute_query(sql_code)

        # Append table to question_and_answer_chat_history
        question_and_answer_chat_history += f"\nAssistant: {str(table_data)}"

        # Get response from description AI agent
        description = retrieveAndGenerate(f"convert list of dictionaries table to natural language description: {table_data}", kb_id, model_arn, session_id)['output']['text']
        # question_and_answer_chat_history += f"\nAssistant: {description}"
        
        return {
            'statusCode': 200,
            'body': {"answer": description}
        }
    else:
        question_and_answer_chat_history += f"\nAssistant: {sanitized_temporary_response}"
        return {
            'statusCode': 200,
            'body': {"answer": sanitized_temporary_response.strip()}
        }