import json

RULES_PATH = "/home/rubengaona/bots/bot_multi_jobs/config/rules.json"

patch3_dict = [
    # --- 1. WEB3 & BLOCKCHAIN ---
    ["Ethereum", ["ethereum", "eth"]],
    ["Web3.js", ["web3.js", "web3js"]],
    ["Ethers.js", ["ethers.js", "ethersjs"]],
    ["Hardhat", ["hardhat"]],
    ["Truffle", ["truffle"]],
    ["IPFS", ["ipfs"]],
    [
        "Smart Contracts",
        ["smart contracts", "smart contract", "contratos inteligentes"],
    ],
    ["Polygon", ["polygon"]],
    ["Solana", ["solana"]],
    ["Chainlink", ["chainlink"]],
    # --- 2. ADVANCED TESTING & QA ---
    ["Mocha", ["mocha"]],
    ["Chai", ["chai"]],
    ["Jasmine", ["jasmine"]],
    ["Karma", ["karma"]],
    ["TestNG", ["testng"]],
    ["XCTest", ["xctest"]],
    ["NUnit", ["nunit"]],
    ["SpecFlow", ["specflow"]],
    ["BrowserStack", ["browserstack", "browser stack"]],
    ["Sauce Labs", ["sauce labs", "saucelabs"]],
    ["Appium", ["appium"]],
    # --- 3. CMS, E-COMMERCE & LOW-CODE ---
    ["WordPress", ["wordpress", "wp"]],
    ["Drupal", ["drupal"]],
    ["Joomla", ["joomla"]],
    ["Magento", ["magento", "adobe commerce"]],
    ["Shopify", ["shopify"]],
    ["WooCommerce", ["woocommerce"]],
    ["Contentful", ["contentful"]],
    ["Strapi", ["strapi"]],
    ["OutSystems", ["outsystems"]],
    ["Mendix", ["mendix"]],
    ["Retool", ["retool"]],
    ["Webflow", ["webflow"]],
    ["Bubble", ["bubble", "bubble.io"]],
    # --- 4. GAME DEV & GRAPHICS ---
    ["Unity", ["unity", "unity3d"]],
    ["Unreal Engine", ["unreal engine", "unreal", "ue4", "ue5"]],
    ["Godot", ["godot"]],
    ["OpenGL", ["opengl"]],
    ["Vulkan", ["vulkan"]],
    ["DirectX", ["directx"]],
    ["WebGL", ["webgl"]],
    # --- 5. BIG DATA & DATA ENGINEERING ---
    ["Apache Hive", ["hive", "apache hive"]],
    ["Presto", ["presto", "prestodb"]],
    ["Trino", ["trino"]],
    ["Amazon Athena", ["athena", "amazon athena", "aws athena"]],
    ["AWS Glue", ["glue", "aws glue"]],
    ["Apache NiFi", ["nifi", "apache nifi"]],
    ["Pentaho", ["pentaho"]],
    ["Power Query", ["power query", "powerquery"]],
    # --- 6. CYBERSECURITY & OFFENSIVE SEC ---
    ["Kali Linux", ["kali", "kali linux"]],
    ["Metasploit", ["metasploit"]],
    ["Burp Suite", ["burp suite", "burpsuite"]],
    ["Nessus", ["nessus"]],
    ["Nmap", ["nmap"]],
    [
        "Pentesting",
        [
            "pentesting",
            "penetration testing",
            "test de penetración",
            "hacking etico",
            "ethical hacking",
        ],
    ],
    ["SOC", ["soc", "security operations center"]],
    # --- 7. WEB SERVERS & PROXIES ---
    ["Apache HTTP Server", ["apache", "apache http server"]],
    ["HAProxy", ["haproxy"]],
    ["Tomcat", ["tomcat", "apache tomcat"]],
    ["IIS", ["iis", "internet information services"]],
    ["Traefik", ["traefik"]],
    ["Caddy", ["caddy"]],
    # --- 8. ENTERPRISE INTEGRATIONS & ESB ---
    ["MuleSoft", ["mulesoft", "mule esb"]],
    ["Boomi", ["boomi", "dell boomi"]],
    ["TIBCO", ["tibco"]],
    ["IBM MQ", ["ibm mq", "websphere mq"]],
    ["Apache Camel", ["apache camel", "camel"]],
    # --- 9. CSS PATTERNS & ARCHITECTURES ---
    ["Styled Components", ["styled components", "styled-components"]],
    ["Emotion", ["emotion"]],
    ["BEM", ["bem", "bem methodology"]],
    ["CQRS", ["cqrs"]],
    ["Event Sourcing", ["event sourcing"]],
    ["BFF", ["bff", "backend for frontend"]],
    [
        "OOP",
        [
            "oop",
            "poo",
            "object oriented programming",
            "programacion orientada a objetos",
        ],
    ],
    ["Functional Programming", ["functional programming", "programacion funcional"]],
]

with open(RULES_PATH, "r", encoding="utf-8") as f:
    rules = json.load(f)

# Convert existing list to a dictionary for easy merging
existing = {item[0]: set(item[1]) for item in rules.get("TECH_TOOLS_CATALOG", [])}

added_canonicals = 0
added_aliases = 0

for new_canonical, new_aliases in patch3_dict:
    if new_canonical not in existing:
        existing[new_canonical] = set()
        added_canonicals += 1

    for alias in new_aliases:
        if alias not in existing[new_canonical]:
            existing[new_canonical].add(alias)
            added_aliases += 1

# Convert back to the list of lists format
final_catalog = [[canonical, list(aliases)] for canonical, aliases in existing.items()]

# Sort alphabetically by canonical name for cleanliness
final_catalog.sort(key=lambda x: x[0].lower())

rules["TECH_TOOLS_CATALOG"] = final_catalog

with open(RULES_PATH, "w", encoding="utf-8") as f:
    json.dump(rules, f, ensure_ascii=False, indent=2)

print("Patch 3.0 injected successfully!")
print(f"Added {added_canonicals} new technologies.")
print(f"Added {added_aliases} new search aliases.")
print(f"Total technologies now in the brain: {len(final_catalog)}")
