# Claude Code Usage Analytics Platform

## 1. Overview

The goal of this assignment is to build an **end-to-end analytics platform** that processes telemetry data from *Claude Code* sessions. You are expected to transform raw event streams into actionable insights regarding developer patterns and user behavior through an interactive dashboard.

## 2. The Dataset

You will be provided with a dataset consisting of anonymized telemetry data, including:

- **Event Streams:** Token usage, code generation requests, and session metadata
- **User Metadata:** Roles and project types associated with the events
- **Format:** Continuous stream format (simulated via JSON/CSV) requiring efficient data ingestion and processing

## 3. Key Requirements

Your solution should demonstrate proficiency in the following areas:

- **Data Processing:** Ingest, clean, and structure the telemetry data. Design a storage mechanism (SQL or NoSQL) that allows for efficient retrieval
- **Analytics & Insights:** Extract meaningful patterns, such as token consumption trends by user role, peak usage times, and common code generation behaviors
- **Visualization:** Build an interactive dashboard (e.g., using Streamlit, Dash, or similar) that presents these insights clearly for different stakeholders
- **Technical Implementation:** Ensure the solution includes basic error handling, data validation, and a clean architectural design

### Optional Enhancements (Bonus)

To further showcase your skills, you may consider implementing one or more of the following:

- **Predictive Analytics:** ML components for trend forecasting or anomaly detection
- **Real-time Capabilities:** Demonstrate how the system could handle live data streaming
- **Advanced Statistical Analysis:** Provide deeper insights into Claude Code usage patterns
- **API Access:** Create API endpoints for programmatic access to the processed data

## 4. AI-First Philosophy (The "Gen AI" Factor)

At Provectus, we embrace the future of software engineering. For this assignment, **we explicitly encourage and reward the use of LLM tools** (such as Claude, ChatGPT, or GitHub Copilot) to build your solution.

- **Objective:** We want to see how effectively you can "orchestrate" AI to generate high-quality code, database schemas, and documentation
- **Evaluation:** Candidates who leverage LLMs to produce functional modules with professional architectural patterns and minimal manual intervention will be evaluated favorably

## 5. Deliverables

To complete the assignment, please submit the following:

1. **Git Repository Link:** Access to the full source code with a clear commit history
2. **README.md:** Detailed setup instructions, an overview of your architecture, and a list of dependencies
3. **Insights Presentation:** A brief PDF presentation (3-5 slides) or a short video demo (max 3 minutes) explaining your findings and the "story" the data tells
4. **LLM Usage Log:** A short document or section in the README detailing which AI tools you used, a few examples of key prompts, and how you validated the AI-generated output

## 6. Evaluation Criteria

- **Functional Thinking:** Ability to translate raw requirements into a working product
- **Technical Execution:** Code quality, stability, and the logic behind your data processing
- **LLM Utilization:** Your skill in using AI tools to accelerate development and ensure best practices
- **Communication:** Clarity of your documentation and your ability to present technical findings
- **Creativity:** Your ability to showcase unique skills, interests, and innovative approaches to the problem
