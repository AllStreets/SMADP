# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: smoke.spec.ts >> SMADP frontend smoke >> chains index → deep view renders
- Location: tests/e2e/smoke.spec.ts:54:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator:  locator('a[href^="/chains/c_"]').first()
Expected: visible
Received: hidden
Timeout:  5000ms

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('a[href^="/chains/c_"]').first()
    9 × locator resolved to <a href="/chains/c_browser-extractor-summarizer" class="text-xs text-brand-300 hover:text-brand-200">↵Open chain →↵</a>
      - unexpected value "hidden"

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - link "Skip to main content" [ref=e2] [cursor=pointer]:
    - /url: "#main"
  - banner [ref=e3]:
    - generic [ref=e4]:
      - link "SMADP" [ref=e5] [cursor=pointer]:
        - /url: /
        - img [ref=e8]
        - generic [ref=e11]: SMADP
      - navigation "Primary" [ref=e12]:
        - list [ref=e13]:
          - listitem [ref=e14]:
            - link "Home" [ref=e15] [cursor=pointer]:
              - /url: /home
          - listitem [ref=e16]:
            - button "Catalog" [ref=e17] [cursor=pointer]:
              - generic [ref=e18]: Catalog
              - img [ref=e19]
          - listitem [ref=e21]:
            - button "Compliance" [ref=e22] [cursor=pointer]:
              - generic [ref=e23]: Compliance
              - img [ref=e24]
          - listitem [ref=e26]:
            - button "Docs" [ref=e27] [cursor=pointer]:
              - generic [ref=e28]: Docs
              - img [ref=e29]
      - generic [ref=e31]:
        - generic [ref=e32]:
          - generic [ref=e33]:
            - img [ref=e34]
            - generic [ref=e36]: no workspace
          - generic [ref=e37]:
            - img [ref=e38]
            - generic [ref=e41]: no user
        - button "choose persona" [ref=e43] [cursor=pointer]:
          - img [ref=e44]
          - generic [ref=e47]: choose persona
        - link "Search /" [ref=e48] [cursor=pointer]:
          - /url: /search
          - img [ref=e49]
          - generic [ref=e52]: Search
          - generic [ref=e53]: /
        - link "Submit agent" [ref=e54] [cursor=pointer]:
          - /url: /submit
  - main [ref=e55]:
    - generic [ref=e56]:
      - text: Catalog
      - heading "Multi-agent compositions" [level=1] [ref=e57]
      - paragraph [ref=e58]: 6 canonical 3+-agent chains with sub-verdict analyses.
    - generic [ref=e59]:
      - group [ref=e60]:
        - generic "Browser → Extract → Summarize Linear toggle panel" [ref=e61] [cursor=pointer]:
          - generic [ref=e62]:
            - img [ref=e63]
            - generic [ref=e66]: Browser → Extract → Summarize
            - generic [ref=e67]: Linear
          - img "toggle panel" [ref=e68]
      - group [ref=e70]:
        - generic "Plan → Fix → Verify Loop Loop toggle panel" [ref=e71] [cursor=pointer]:
          - generic [ref=e72]:
            - img [ref=e73]
            - generic [ref=e76]: Plan → Fix → Verify Loop
            - generic [ref=e77]: Loop
          - img "toggle panel" [ref=e78]
      - group [ref=e80]:
        - generic "Orchestrator Fan-out + Merge Star toggle panel" [ref=e81] [cursor=pointer]:
          - generic [ref=e82]:
            - img [ref=e83]
            - generic [ref=e86]: Orchestrator Fan-out + Merge
            - generic [ref=e87]: Star
          - img "toggle panel" [ref=e88]
      - group [ref=e90]:
        - generic "Planner → Executor → Critic Linear toggle panel" [ref=e91] [cursor=pointer]:
          - generic [ref=e92]:
            - img [ref=e93]
            - generic [ref=e96]: Planner → Executor → Critic
            - generic [ref=e97]: Linear
          - img "toggle panel" [ref=e98]
      - group [ref=e100]:
        - generic "RAG → Reason → Tool Linear toggle panel" [ref=e101] [cursor=pointer]:
          - generic [ref=e102]:
            - img [ref=e103]
            - generic [ref=e106]: RAG → Reason → Tool
            - generic [ref=e107]: Linear
          - img "toggle panel" [ref=e108]
      - group [ref=e110]:
        - generic "Research → Write → Cite Linear toggle panel" [ref=e111] [cursor=pointer]:
          - generic [ref=e112]:
            - img [ref=e113]
            - generic [ref=e116]: Research → Write → Cite
            - generic [ref=e117]: Linear
          - img "toggle panel" [ref=e118]
  - contentinfo [ref=e120]:
    - generic [ref=e121]:
      - generic [ref=e122]:
        - generic [ref=e123]:
          - generic [ref=e124]:
            - img [ref=e125]
            - generic [ref=e128]: SMADP
          - paragraph [ref=e129]: Safe Multi-Agent Deployment Platform. Auditable, evidence-cited verdicts on whether two AI agents can safely run together. Apache-2.0. Catalog is publicly redistributable.
        - generic [ref=e130]:
          - heading "Catalog" [level=4] [ref=e131]
          - list [ref=e132]:
            - listitem [ref=e133]:
              - link "Browse agents" [ref=e134] [cursor=pointer]:
                - /url: /agents
            - listitem [ref=e135]:
              - link "Compatibility matrix" [ref=e136] [cursor=pointer]:
                - /url: /matrix
            - listitem [ref=e137]:
              - link "All verdicts" [ref=e138] [cursor=pointer]:
                - /url: /verdicts
            - listitem [ref=e139]:
              - link "Search" [ref=e140] [cursor=pointer]:
                - /url: /search
        - generic [ref=e141]:
          - heading "Methodology" [level=4] [ref=e142]
          - list [ref=e143]:
            - listitem [ref=e144]:
              - link "How verdicts are produced" [ref=e145] [cursor=pointer]:
                - /url: /methodology
            - listitem [ref=e146]:
              - link "Risk taxonomy" [ref=e147] [cursor=pointer]:
                - /url: /risks
            - listitem [ref=e148]:
              - link "Framework mappings" [ref=e149] [cursor=pointer]:
                - /url: /frameworks
            - listitem [ref=e150]:
              - link "Chronicle (audit log)" [ref=e151] [cursor=pointer]:
                - /url: /chronicle
        - generic [ref=e152]:
          - heading "Project" [level=4] [ref=e153]
          - list [ref=e154]:
            - listitem [ref=e155]:
              - link "GitHub repo" [ref=e156] [cursor=pointer]:
                - /url: https://github.com/AllStreets/SMADP
            - listitem [ref=e157]:
              - link "Submit an agent" [ref=e158] [cursor=pointer]:
                - /url: /submit
            - listitem [ref=e159]:
              - link "Evidence policy" [ref=e160] [cursor=pointer]:
                - /url: /methodology#evidence-policy
            - listitem [ref=e161]:
              - link "Composite scoring" [ref=e162] [cursor=pointer]:
                - /url: /methodology#scoring
        - generic [ref=e163]:
          - heading "Sibling" [level=4] [ref=e164]
          - link "NEXUS" [ref=e165] [cursor=pointer]:
            - /url: https://github.com/AllStreets/ONEXUS
      - generic [ref=e166]:
        - paragraph [ref=e167]: © 2026 SMADP contributors. Apache-2.0.
        - paragraph [ref=e168]: catalog · git-backed · evidence-first
```