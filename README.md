# LegalHelp
LegalHelp is a Python application that helps users understand legal documents by extracting text, generating simple-language summaries, and providing audio output in the user's preferred language.

# Tech Stack
It uses python only. It uses these following modules.
- streamlit
- pandas
- numpy

# Description
People with limited literacy - those who are unable to read and write, and those who may not have enough time to spend in their schedule, often end up not being able to read through possibly important legal documents. 
This is where LegalHelp comes in. LegalHelp works like so:

1. It takes in photographic input of the legal documents, and an audio query from the user. These are then parsed and sent to an LLM which can process these into a structured output, based on a static prompt given, and the information given by the user.

2. These answers are displayed as output on screen in whatever language the user spoke in / gave the reuqest in.
