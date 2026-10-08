# wsparql

This project goal is to evaluate https://ollaya.dev/ with a POC as follow.

## Goal

Allow a user to ask a question in natural language and automatically select the most relevant predefined SPARQL query to execute on a knowledge graph.
The system does not generate SPARQL.
It only chooses among trusted, existing queries.

## Input

The POC relies on:

- a TBOX ontology describing the domain;
- an ABOX dataset containing the actual data;
- a catalog of predefined SPARQL queries;
- a controlled dictionary of tags describing concepts and user intentions.

## Decision process

Natural language question
↓
Detect relevant tags with Ollaya
↓
Identify the most relevant SPARQL queries
↓
Ollaya selects the best candidate
↓
Extract query parameters
↓
Execute SPARQL on the ABOX
↓
Return the result

## Technical stack

- python, uv
- one Makefile to centralize all tasks

## Role of the Ontology

The TBOX provides additional semantic knowledge.

For example, if Researcher is a subclass of Person, the system can use this relationship during query selection without asking the AI model to rediscover it.

## Expected Demo

The demo should show:

- the user question;
- the detected tags and confidence scores;
- the candidate SPARQL queries;
- the selected query;
- the extracted parameters;
- the final result returned from the ABOX.

The system must also be able to answer "no suitable query" when no predefined query matches the question.

## POC Success Criteria

The POC is successful if it demonstrates that natural-language questions can be reliably routed to predefined SPARQL queries while keeping the execution layer controlled, explainable and testable.
