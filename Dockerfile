FROM python:3.11.5-slim

RUN pip install pipenv
RUN apt-get update && apt-get install -yq git

WORKDIR /discord-modlinkbot

COPY Pipfile Pipfile.lock ./
RUN pipenv install --deploy --ignore-pipfile

COPY . .

CMD [ "pipenv", "run", "bot" ]