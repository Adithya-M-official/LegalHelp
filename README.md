# LegalHelp
An app made fully in python that can help even the illiterate with reading legal reports and the summarisation and audio-output of the summary and points it sees.

# Tech Stack
It uses python only. It uses these following modules.
- streamlit
- pandas
- numpy

# Description
Ileterate people that cannot read any legal documents, or those that do not have much time on their hands to shuffle through their legal documents, face the common issue of not being able to read these documents. Thus LegalHelp works to alleviate this issue, but doing a few things in particular.

1. It takes in photographic input of the legal documents, and an audio query from the user. These are then parsed and sent to an LLM which can process these into a structured output, based on a static prompt given, and the information given by the user.

2. These answers are displayed as output on screen in whatever language the user spoke in / gave the reuqest in.
