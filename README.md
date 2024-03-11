# Notes
Frontend for Leo testing is on streamlit

Same logic for Bruno React and Testing

Different scripts

python matlib
react recharts

write tests for react and recharts

this is testing code

pass bruno json files



1. user asks general question -> LLM respond to an answer
2. user asks question with keyword table-> 2nd LLM that makes SQL -> PostgresDB on an Xnode -> Retrieves result -> Display to user the result
3. user asks question with keyword chart ->same as above ->  PostgresDB results -> JSON -> recharts
JSON -> 3rd LLM that summarizes it
4. save context i.e pass previous responses to llm -> use question 1 llm
5. user asks both table and chart -> question 2 flow -> questions 3 flow

tests:

different types of user questions generate relevant chart type



ai safety -> guardrails -> censor responses -> only answer blockchain stuff


Implement AI agents hitting the ground running
Implement AI safety for natural language Q&A
Testing various questions for tables and charts
Fine tuning
Implement in AWS ->  Bedrock
AWS cost estimation for hosting LLM

Need a database person for the following:

need to change table and columns in Postgres -> human readable


look into redis data and add it to postgres or connect to redis


need to add data in Postgres as its missing data


need to update Postgres to more recent data 29th Feb 2024 


need to add more data in Postgres


need a way to optimize speed connection to one Postgres -> indexing, cacching, optimizing
