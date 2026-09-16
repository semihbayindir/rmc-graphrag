# Setup

## Prerequisites

- Docker with Docker Compose
- Internet access (OpenAI API, Neo4j APOC plugin download)
- A Neo4j database dump (`neo4j.dump`), see [Creating the dump](#creating-the-dump)

## 1. Configure the environment

```bash
cp .env.example .env
```

Set the required values in `.env`:

- `OPENAI_API_KEY`
- `NEO4J_V2_PASSWORD`

Set `NEO4J_V2_PASSWORD` before the first start; Neo4j stores it when the database volume is created.

## 2. Load the database

Place `neo4j.dump` in the `backups/` directory, then run:

```bash
docker compose run --rm --no-deps -v "$PWD/backups:/backups" neo4j \
  neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true
```

Neo4j must not be running during the load. On an existing installation, run `docker compose stop neo4j` first.

## 3. Start the services

```bash
mkdir -p data
docker compose up -d --build
```

| Service | URL |
|---|---|
| Web | http://localhost:3000 |
| API | http://localhost:8000 |
| Neo4j Browser | http://localhost:7474 |

## Creating the dump

Run on an existing installation. The file is written to `backups/neo4j.dump`.

```bash
docker compose stop neo4j
docker compose run --rm --no-deps -v "$PWD/backups:/backups" neo4j \
  neo4j-admin database dump neo4j --to-path=/backups --overwrite-destination=true
docker compose start neo4j
```

The dump contains customer data and is excluded from Git.
