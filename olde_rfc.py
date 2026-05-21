#!/usr/bin/env python3
"""
Olde RFC - Transform technical specs into medieval manuscripts.

Usage:
    python olde_rfc.py input.md -o scroll.html
    python olde_rfc.py input.md -o scroll.pdf       # requires weasyprint
    python olde_rfc.py --mock -o scroll.html         # test template without API
    cat spec.md | python olde_rfc.py -o scroll.html  # read from stdin
"""

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic
from jinja2 import Template


SYSTEM_PROMPT = """\
You are a monastic scribe of great wit and erudition. You receive modern technical \
documents (RFCs, specs, proposals, design docs) and transcribe them as medieval manuscripts.

You MUST output valid JSON with this exact structure:
{
  "title": "A Latin or pseudo-Latin title for the document",
  "subtitle": "A single flowing sentence of archaic English beginning with 'Wherein...' (no line breaks — the browser will wrap naturally)",
  "metadata": {
    "sphere": "The domain/area in Latin-ized terms (e.g. 'Metrica \u00b7 Tracta \u00b7 Acta')",
    "locus": "Where it runs/applies in archaic terms (e.g. 'Cloud of AWS')",
    "aim": "The goals in Latin-ized terms (e.g. 'Stabilitas \u00b7 Operatio \u00b7 Aurum')",
    "status": "Document status in Latin: Proposito (Proposed), Acceptum (Accepted), Reiectum (Rejected), Supersessum (Superseded)"
  },
  "chapters": [
    {
      "number": "Primum",
      "subtitle": "A short English gloss like 'Of Beginnings'",
      "heading": "A Latin or pseudo-Latin chapter title like 'Summa Brevis'",
      "body": "The rewritten content in mock-medieval English. Use \\n\\n for paragraph breaks."
    }
  ]
}

CHAPTER NUMBERING in Latin ordinals:
Primum, Secundum, Tertium, Quartum, Quintum, Sextum, Septimum, Octavum, Nonum, Decimum.

SECTION MAPPING (adapt as needed, aim for 4-8 chapters):
- Summary/Abstract -> "Summa Brevis" (always chapter Primum)
- Background/Context -> "De Rebus Praeteritis" (Of Past Things)
- Problem Statement -> "De Malis Praesentibus" (Of Present Evils)
- Proposed Solution -> "Remedium Propositum" (The Proposed Remedy)
- Architecture/Design -> "De Architectura" (Of Architecture)
- Implementation -> "De Opere Faciundo" (Of the Work to Be Done)
- Migration/Rollout -> "De Migratione" (Of the Migration)
- Risks -> "De Periculis" (Of Dangers)
- Alternatives -> "De Viis Alteris" (Of Other Paths)
- Timeline -> "De Temporibus" (Of Times)
- Cost -> "De Tributo" (Of Tribute)
- Conclusion -> "Peroratio" (The Final Plea)

STYLE RULES for medieval English body text:
- Use archaic verb forms: "hath", "doth", "speaketh", "-eth" suffixes, "wherein", "thereof", "unto", "whilst"
- Personify tools and services as characters with epithets: "Prometheus the Steward of Metrics", "Kubernetes the Orchestrator of Vessels"
- Use medieval metaphors for technical concepts:
  Costs/pricing -> "tribute", "tithe", "the royal purse"
  Servers -> "keeps", "strongholds", "towers"
  Databases -> "great vaults", "scriptoria"
  APIs -> "proclamations", "royal decrees"
  Monitoring -> "the vigil", "watchkeeping"
  Deployment -> "summoning", "mustering"
  Testing -> "trial by ordeal", "the proving grounds"
  Bugs -> "gremlins", "foul spirits"
  Users -> "the townsfolk", "denizens of the realm"
  Microservices -> "guilds", "lesser fiefdoms"
  Load balancer -> "the Gate Keeper"
  Cache -> "the scribe's quick-memory"
  CI/CD -> "the Rite of Continuous Summoning"
  Encryption -> "the arcane wards"
  Authentication -> "proving one's heraldry"
- Keep actual product names, acronyms, and technical identifiers intact (AWS, S3, gRPC, etc.)
- Be genuinely witty and entertaining while preserving ALL technical substance
- Every technical detail from the original MUST appear - humor enhances, never replaces
- The tone: a blend of Monty Python, Umberto Eco, and a real RFC - learned, pompous, and deeply funny
- Aim for rich, flowing prose - no bullet points or lists in the output

Output ONLY the JSON object, no other text.
"""


MOCK_DATA = {
    "title": "De Observabilitate Nostra",
    "subtitle": (
        "Wherein the Bill of Datadog is Found Wanting, "
        "& a New Order Established upon Prometheus, Grafana, "
        "Loki, Honeycomb, & the Faithful Agent Alloy."
    ),
    "metadata": {
        "sphere": "Metrica \u00b7 Tracta \u00b7 Acta",
        "locus": "Cloud of AWS",
        "aim": "Stabilitas \u00b7 Operatio \u00b7 Aurum",
        "status": "Proposito",
    },
    "chapters": [
        {
            "number": "Primum",
            "subtitle": "Of Beginnings",
            "heading": "Summa Brevis",
            "body": (
                "Datadog hath served us with honour, yet its tribute groweth "
                "wearisome to the purse. We propose to remove our trust unto a "
                "federation of three: Prometheus the Steward of Metrics, kept by "
                "Amazon; Loki the Keeper of Logs, dwelling upon S3; and Honeycomb, "
                "who alone among them speaketh fluently the tongue of Tracts. Above "
                "them all standeth Alloy, the faithful agent, who gathereth every "
                "signal and dispatcheth it whither it ought go.\n\n"
                "This transformation shall unfold across three moons, beginning with "
                "the metrics vigil and culminating in the full retirement of "
                "Datadog from our realm. The royal purse shall thereby be lightened "
                "by some two hundred and twenty-eight thousand crowns per annum."
            ),
        },
        {
            "number": "Secundum",
            "subtitle": "Of Present Evils",
            "heading": "De Malis Praesentibus",
            "body": (
                "The tribute demanded by Datadog hath swollen beyond all reason. "
                "What once was a modest tithe of twelve thousand crowns per moon "
                "now commandeth five-and-thirty thousand, with projections most dire "
                "showing seven-and-forty thousand by the second quarter. The beast "
                "feedeth upon every new host we provision, every trace we emit, every "
                "log line our services cry into the void.\n\n"
                "Moreover, the vendor locketh us within its walls most cunningly. Our "
                "dashboards, our alerts, our carefully wrought queries\u2014all are held "
                "hostage within its proprietary keep. Should we ever wish to depart, "
                "we must rebuild all from naught, as a scribe forced to re-copy an "
                "entire library when his monastery changeth allegiance."
            ),
        },
        {
            "number": "Tertium",
            "subtitle": "Of the Proposed Remedy",
            "heading": "Remedium Propositum",
            "body": (
                "We do hereby propose the adoption of an open-source observability "
                "stack, composed thus:\n\n"
                "For METRICS: Prometheus, managed through Amazon's own Managed "
                "Service, shall collect and store all measurements of our systems' "
                "health. Grafana shall provide the looking-glass through which we "
                "peer at these numbers, for a tribute of but five thousand crowns "
                "per moon.\n\n"
                "For LOGS: Loki, that clever daemon, shall index our logs with "
                "naught but their labels, storing the full text upon S3 at a "
                "fraction of Datadog's tribute\u2014a mere three thousand crowns.\n\n"
                "For TRACES: Honeycomb shall receive our distributed traces, for "
                "its query engine hath no equal in the swift unravelling of "
                "latency's mysteries, at eight thousand crowns per moon.\n\n"
                "Above all these, OpenTelemetry Collector\u2014called Alloy in "
                "Grafana's tongue\u2014shall serve as the universal gatherer, "
                "accepting signals in any format and routing them to their "
                "appointed destinations."
            ),
        },
        {
            "number": "Quartum",
            "subtitle": "Of the Great Migration",
            "heading": "De Migratione",
            "body": (
                "The migration shall proceed in three phases, each spanning four "
                "weeks, so that no vigil goeth unwatched and no alarm unheeded "
                "during the transition.\n\n"
                "In the FIRST MOON, we shall deploy AMP and Grafana, and configure "
                "Alloy to dual-ship metrics unto both Datadog and Prometheus. The "
                "critical dashboards shall be recreated in Grafana, and data parity "
                "shall be validated most thoroughly.\n\n"
                "In the SECOND MOON, the Loki cluster shall be raised, and log "
                "shipping configured through Alloy. All log-based alerts shall be "
                "migrated, and the query capabilities proved sufficient.\n\n"
                "In the THIRD MOON, Honeycomb shall be brought into service. The "
                "APM dashboards and SLOs shall be migrated, the Datadog agents "
                "decommissioned, and the contract cancelled with great ceremony "
                "and perhaps a small feast."
            ),
        },
        {
            "number": "Quintum",
            "subtitle": "Of Dangers",
            "heading": "De Periculis",
            "body": (
                "No undertaking of this magnitude is without peril. We have "
                "identified these threats and their remedies:\n\n"
                "DATA LOSS during the migration is guarded against by the practice "
                "of dual-shipping, wherein every signal is sent to both the old "
                "and new systems until confidence is established.\n\n"
                "ALERT GAPS are forestalled by running both systems in parallel "
                "throughout the transition, so that no gremlin may pass undetected "
                "through the changing of the guard.\n\n"
                "The RAMP-UP of our engineers upon the new tools shall require "
                "approximately one week of training per team\u2014a modest investment "
                "against the annual savings of two hundred and twenty-eight thousand "
                "crowns.\n\n"
                "LOKI'S SCALING temperament must be managed with care, for it "
                "groweth vexed when presented with labels of high cardinality. "
                "A careful schema design shall keep the beast content."
            ),
        },
    ],
}


def transform_to_medieval(text: str, model: str = "claude-sonnet-4-6") -> dict:
    """Send a technical doc to Claude and receive structured medieval manuscript data."""
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Transform this technical document into a medieval manuscript:\n\n"
                    + text
                ),
            }
        ],
    )
    content = msg.content[0].text

    # Try direct JSON parse first, then extract from code fence
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Could not parse LLM response as JSON:\n{content[:500]}")


def render_html(data: dict, template_path: Path | None = None) -> str:
    """Render medieval manuscript data to HTML using the Jinja2 template."""
    if template_path is None:
        template_path = Path(__file__).parent / "template.html"
    tmpl = Template(template_path.read_text())
    return tmpl.render(**data)


def main():
    parser = argparse.ArgumentParser(
        description="Transform technical specs into medieval manuscripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python olde_rfc.py rfc.md -o scroll.html\n"
            "  python olde_rfc.py rfc.md -o scroll.pdf\n"
            "  python olde_rfc.py --mock -o demo.html\n"
            "  cat rfc.md | python olde_rfc.py -o scroll.html\n"
        ),
    )
    parser.add_argument(
        "input", nargs="?", default="-", help="Input file (default: stdin)"
    )
    parser.add_argument("-o", "--output", help="Output file (.html or .pdf)")
    parser.add_argument(
        "--mock", action="store_true", help="Use built-in mock data (no API call)"
    )
    parser.add_argument(
        "--json-input", metavar="FILE", help="Use pre-generated JSON file as input"
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Print the structured JSON and exit",
    )
    parser.add_argument("--template", metavar="FILE", help="Custom HTML template path")
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude model (default: claude-sonnet-4-6)",
    )
    args = parser.parse_args()

    # --- Obtain structured data ---
    if args.mock:
        data = MOCK_DATA
    elif args.json_input:
        data = json.loads(Path(args.json_input).read_text())
    else:
        if args.input == "-":
            if sys.stdin.isatty():
                parser.print_help()
                sys.exit(1)
            text = sys.stdin.read()
        else:
            text = Path(args.input).read_text()
        if not text.strip():
            print("Error: empty input", file=sys.stderr)
            sys.exit(1)
        data = transform_to_medieval(text, model=args.model)

    if args.json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    # --- Render ---
    template_path = Path(args.template) if args.template else None
    html = render_html(data, template_path)

    if not args.output:
        print(html)
    elif args.output.endswith(".pdf"):
        try:
            from weasyprint import HTML as WeasyprintHTML

            WeasyprintHTML(
                string=html, base_url=str(Path(__file__).parent)
            ).write_pdf(args.output)
            print(f"Written to {args.output}", file=sys.stderr)
        except ImportError:
            print(
                "weasyprint is required for PDF output: pip install weasyprint",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        Path(args.output).write_text(html)
        print(f"Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
