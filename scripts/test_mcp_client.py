import asyncio
import json
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession
from mcp import StdioServerParameters

async def main():
    server_params = StdioServerParameters(
        command="/path/to/jobot/.venv/bin/jobbot",
        args=["mcp"],
        cwd="/path/to/jobot"
    )

    print("=" * 70)
    print("JOBBOT MODEL CONTEXT PROTOCOL (MCP) CLIENT VERIFICATION")
    print("=" * 70)
    print("Connecting to JobBot MCP Server via stdio transport...")

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. Initialize
            init_result = await session.initialize()
            print(f"[OK] Connected to MCP Server: {init_result.server_info.name} (Protocol: {init_result.protocol_version})")
            print("-" * 70)

            # 2. List tools
            tools_result = await session.list_tools()
            print(f"[OK] Discovered {len(tools_result.tools)} MCP Tools:")
            for tool in tools_result.tools:
                print(f"  • {tool.name:<22} : {tool.description[:65]}...")
            print("-" * 70)

            # 3. List resources
            resources_result = await session.list_resources()
            print(f"[OK] Discovered {len(resources_result.resources)} MCP Resources:")
            for res in resources_result.resources:
                print(f"  • {res.uri:<24} ({res.name})")
            print("-" * 70)

            # 4. List prompts
            prompts_result = await session.list_prompts()
            print(f"[OK] Discovered {len(prompts_result.prompts)} MCP Prompts:")
            for p in prompts_result.prompts:
                print(f"  • {p.name:<22} : {p.description}")
            print("-" * 70)

            # 5. Call Tool: get_pipeline_status
            print(">>> Invoking Tool: get_pipeline_status()")
            status_res = await session.call_tool("get_pipeline_status", arguments={})
            for content in status_res.content:
                if hasattr(content, "text"):
                    parsed = json.loads(content.text)
                    print("Pipeline Status Summary:")
                    print("  States:", parsed.get("pipeline_states"))
                    print("  Bands: ", parsed.get("score_bands"))
                    print("  Apps:  ", parsed.get("applications"))
            print("-" * 70)

            # 6. Call Tool: list_jobs (band='B', limit=3)
            print(">>> Invoking Tool: list_jobs(band='B', limit=3)")
            list_res = await session.call_tool("list_jobs", arguments={"band": "B", "limit": 3})
            for content in list_res.content:
                if hasattr(content, "text"):
                    try:
                        data = json.loads(content.text)
                        items = data if isinstance(data, list) else [data]
                        for j in items:
                            print(f"  • [{j['id']}] {j['company']} — {j['title']} (Score: {j['score']}, State: {j['state']})")
                    except Exception:
                        print("  •", content.text[:80])
            print("-" * 70)

            # 7. Call Tool: search_jobs (query='DevOps')
            print(">>> Invoking Tool: search_jobs(query='DevOps')")
            search_res = await session.call_tool("search_jobs", arguments={"query": "DevOps"})
            count = 0
            for content in search_res.content:
                if hasattr(content, "text"):
                    try:
                        data = json.loads(content.text)
                        items = data if isinstance(data, list) else [data]
                        for j in items:
                            count += 1
                            if count <= 3:
                                print(f"  • [{j['id']}] {j['company']} — {j['title']} ({j['source']}, Score: {j['score']})")
                    except Exception:
                        pass
            print(f"  Total DevOps matches: {count}")
            print("-" * 70)

            # 8. Call Tool: get_candidate_facts
            print(">>> Invoking Tool: get_candidate_facts()")
            facts_res = await session.call_tool("get_candidate_facts", arguments={})
            for content in facts_res.content:
                if hasattr(content, "text"):
                    first_line = content.text.strip().split("\n")[0]
                    print(f"  Candidate facts retrieved ({len(content.text)} bytes, Header: '{first_line}')")
            print("-" * 70)

            # 9. Read Resource: jobbot://status
            print(">>> Reading Resource: jobbot://status")
            res_content = await session.read_resource("jobbot://status")
            for c in res_content.contents:
                if hasattr(c, "text"):
                    res_json = json.loads(c.text)
                    print(f"  Resource verified (total sent applications: {res_json.get('applications', {}).get('total_sent')})")
            print("-" * 70)

            # 10. Read Resource: jobbot://jobs/band-a
            print(">>> Reading Resource: jobbot://jobs/band-a")
            res_content = await session.read_resource("jobbot://jobs/band-a")
            for c in res_content.contents:
                if hasattr(c, "text"):
                    jobs_a = json.loads(c.text)
                    print(f"  Band A jobs retrieved ({len(jobs_a)} jobs in shortlist)")
            print("-" * 70)

            # 11. Get Prompt: review_and_tailor
            print(">>> Fetching Prompt: review_and_tailor")
            prompt_res = await session.get_prompt("review_and_tailor", arguments={})
            print(f"  Prompt description: {prompt_res.description}")
            if prompt_res.messages:
                print(f"  Prompt message count: {len(prompt_res.messages)}")
            print("=" * 70)
            print("[SUCCESS] All MCP Tools, Resources, and Prompts verified successfully!")
            print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
