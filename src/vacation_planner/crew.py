from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import SerperDevTool
from crewai import LLM

#1 Memory - imports
import boto3
import uuid
from datetime import datetime

import os
from dotenv import load_dotenv

load_dotenv()

# ---------- #1 Agentcore imports  --------------------
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

os.environ["SERPER_API_KEY"] = os.environ.get('SERPER_API_KEY')

serper_dev_tool=SerperDevTool()
llm=LLM(model=os.environ.get('MODEL'), aws_region_name=os.environ.get('AWS_REGION_NAME'))
memoryId = os.environ.get('MEMORY_ID')

#2 Memory client initialization
memory_client = boto3.client('bedrock-agentcore', region_name='us-east-1')

@CrewBase
class VacationPlanner():
    """VacationPlanner crew"""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def vacation_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['vacation_researcher'], # type: ignore[index]
            verbose=True,
            tools=[serper_dev_tool],
            llm=llm
        )

    @agent
    def itinerary_planner(self) -> Agent:
        return Agent(
            config=self.agents_config['itinerary_planner'], # type: ignore[index]
            verbose=True,
            llm=llm
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'], # type: ignore[index]
        )

    @task
    def reporting_task(self) -> Task:
        return Task(
            config=self.tasks_config['reporting_task'], # type: ignore[index]
            output_file='report.md'
        )

    @crew
    def crew(self) -> Crew:
        """Creates the VacationPlanner crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
        )


@app.entrypoint
def agent_invocation(payload, context):
    """Handler for agent invocation"""
    print(f'Payload: {payload}')
    try:
        # Extract user input from payload
        user_input = payload.get("topic", "Tokyo, Japan")
        print(f"Processing vacation destination: {user_input}")

        #3 Memory - Retrieve past memory
        session_id = getattr(context, "sessionId", "default_session")

        previous_events = memory_client.list_events(
            memoryId=memoryId,
            actorId='user',
            sessionId=session_id,
            maxResults=3
        )
        
        # Crew Execution - Creates an instance of the VacationPlanner class and run crew method
        research_crew_instance = VacationPlanner()
        crew = research_crew_instance.crew()

        # Send input to Agent with previous memory
        events = previous_events.get('events', [])
        formatted_conversations = []
        for event in events:
            formatted_event = {}
            for key, value in event.items():
                if isinstance(value, datetime):
                    formatted_event[key] = value.isoformat()
                else:
                    formatted_event[key] = value
            formatted_conversations.append(formatted_event)

        # Starts the sequential agent workflow
        result = crew.kickoff(inputs={'topic': user_input, 'previous_conversations': formatted_conversations})

        #5 Memory storage - Save current interaction
        memory_client.create_event(
            memoryId=memoryId,
            actorId='user',
            sessionId=session_id,
            eventTimestamp=datetime.utcnow(),
            payload=[
                {
                    "conversational": {
                        "content": {"text": user_input},
                        "role": "USER"
                    }
                },
                {
                    "conversational": {
                        "content": {"text": result.raw},
                        "role": "ASSISTANT"
                    }
                }
            ],
            clientToken=str(uuid.uuid4())
        )

        print("Context:\n-------\n", context)
        print("Result Raw:\n*******\n", result.raw)
        
        # Safely access json_dict if it exists
        if hasattr(result, 'json_dict'):
            print("Result JSON:\n*******\n", result.json_dict)
        
        return {"result": result.raw}
        
    except Exception as e:
        print(f'Exception occurred: {e}')
        return {"error": f"An error occurred: {str(e)}"}

# Local test function
def test_local():
    """Test the crew locally without AgentCore"""
    try:
        crew_instance = VacationPlanner()
        crew = crew_instance.crew()
        result = crew.kickoff(inputs={'topic': 'Plan a vacation to Germany'})
        print("Result:", result.raw)
        return result
    except Exception as e:
        print(f"Error: {e}")
        return None    

if __name__ == "__main__":
    #test_local()
    app.run(port=8080)