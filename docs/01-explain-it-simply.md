# SupportDesk — explained simply

SupportDesk is a customer-support "agent" — an intelligent program that reads a
customer's message, figures out what they need, and either answers them or hands
them to a human, all while following safety rules.

## The problem it solves

When a customer writes in ("I was charged twice, can you refund me?"), a support
team has to:

1. Work out what the customer wants (refund? password reset? a technical bug?).
2. Look up the customer's account and invoice.
3. Decide if the request is allowed (a $2,000 refund needs a manager's OK).
4. Write a correct, polite reply that doesn't promise too much or leak private data.
5. Escalate to a human when it can't handle the request safely.

SupportDesk automates steps 1–4 with six specialized AI agents and routes step 5
to a human automatically.

## The six agents

| Agent | What it does |
|-------|--------------|
| **Router** | Reads the message and decides which specialist should handle it (billing, technical, account, or escalation), plus how urgent it is and how confident it is. |
| **Billing** | Handles invoices, refunds, and plan changes. |
| **Technical** | Searches the help articles, checks whether the service is up or down, and files bug tickets. |
| **Account** | Looks up your own account and sends password-reset links. |
| **Escalation** | Creates tickets and notifies a human agent when the issue needs a person. |
| **Critic** | Reads every draft reply before it's sent and checks it for mistakes, leaked private data, or over-promising. |

## How a message flows through the system

1. **Router** classifies the message and picks a specialist.
2. The **specialist** answers using its tools (looking up invoices, searching help articles, etc.).
3. The **Critic** reviews the draft reply. If something is wrong, it asks for a fix or escalates.
4. The final reply is sent to the customer.

If a refund is larger than a set limit (for example $100), the system pauses and
asks a human to approve or reject it before anything happens. If the router isn't
sure, or if the Critic rejects the reply, the conversation is escalated to a
human with a full summary.

## Safety by design

- **No customer can see another customer's data.** The database layer only ever returns rows that belong to the person asking.
- **No secret keys in code.** All configuration (API keys, database URLs, limits) comes from environment variables.
- **Private data is redacted** before it's written to logs.
- **Prompt-injection attempts are blocked.** Messages that try to hijack the system ("ignore all previous instructions...") are rejected.

## How to run it

```bash
# Install and seed reproducible test data (one command seeds everything)
pip install -e ".[dev]"
python -m supportdesk.cli seed

# Start the API
python -m supportdesk.cli serve

# Or run the whole thing with Docker
docker compose up --build
```

Then send messages to `POST http://localhost:8000/chat`.

## Who this is for

This project is a portfolio piece designed to be explained in an AI Solutions or
Full-Stack Developer interview. The `docs/` folder contains a full interview kit:
architecture walkthrough, design decisions, interview Q&A, a demo script, a code
tour, a testing strategy, and an honest look at limitations.
