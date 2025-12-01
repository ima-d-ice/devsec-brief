# ask.py

import argparse
from src.rag import answer_question


def main():
    parser = argparse.ArgumentParser(
        description="DevSec Brief – RAG-powered dev + cybersec news assistant (Groq backend)."
    )

    parser.add_argument(
        "query",
        nargs="*",
        help="Your question about recent web dev / cybersec news.",
    )

    parser.add_argument(
        "--topic",
        "-t",
        choices=["webdev", "cybersec", "all"],
        default="all",
        help="Limit results to webdev, cybersec, or all (default: all).",
    )

    parser.add_argument(
        "--k",
        type=int,
        default=6,
        help="Number of relevant articles to retrieve (default: 6).",
    )

    args = parser.parse_args()

    # If no query given, ask interactively
    if not args.query:
        try:
            q = input("Enter your question: ").strip()
        except KeyboardInterrupt:
            print("\nAborted.")
            return
    else:
        q = " ".join(args.query).strip()

    if not q:
        print("No question provided.")
        return

    topic = None if args.topic == "all" else args.topic

    print(f"\nQUESTION: {q}")
    if topic:
        print(f"TOPIC: {topic}")
    print("\nThinking...\n")

    result = answer_question(q, topic=topic, k=args.k)

    print("ANSWER:\n")
    print(result["answer"])
    print("\n" + "=" * 80 + "\n")
    print("SOURCES:")

    sources = result.get("sources") or []
    if not sources:
        print("  (no sources returned)")
        return

    for s in sources:
        title = s.get("title") or "(no title)"
        url = s.get("url") or "(no url)"
        src = s.get("source") or "(unknown source)"
        cat = s.get("category") or "-"
        print(f"- [{cat}] {src} → {title}")
        print(f"    {url}")


if __name__ == "__main__":
    main()

