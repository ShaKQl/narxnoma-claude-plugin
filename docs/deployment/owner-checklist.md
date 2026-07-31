# Narxnoma — Owner Setup Checklist

**Everything on this page needs a human.** These are the steps I cannot do myself: they
involve payment, identity, or account creation. Once they are done and you hand me the
three things in §4, I can build and run the whole platform without further input from you.

Work through it top to bottom. Total time: about an hour, plus DNS propagation.

**Decisions already made (2026-07-27), so you don't have to make them while buying:**

| | |
|---|---|
| Domain | **`narxnoma.uz`** (plus `narxnoma.com` defensively) |
| Registrar + host | **PS Cloud Services — `pscloud.uz`** — both from one vendor |
| Server | Tashkent / TAS-IX, Ubuntu 24.04 LTS, 4 vCPU / 8 GB / 80–160 GB SSD |
| DNS + TLS | Cloudflare free tier + Let's Encrypt |
| Starting from | Nothing — no existing domain, server, or Cloudflare account |

> **Never paste a password, private key, or API token into our chat.** Everything secret
> goes into a file on your machine, and you tell me only the *path*. §4 gives the exact
> commands. If a secret does end up in chat, treat it as compromised and rotate it.

---

## 1. Buy the domain

### What to buy

| | |
|---|---|
| **Primary** | `narxnoma.uz` |
| **Defensive** | `narxnoma.com` — optional but cheap; stops someone else taking the brand |

`.uz` is the right primary. Your competitor runs `uzprice.uz`, Uzbek shoppers trust `.uz`,
and it ranks better for local queries. **`.uz` does not require local presence** — no
company registration, no VAT number, no residency. Terms run 1–10 years.

### Where to buy

**Buy `narxnoma.uz` from [PS Cloud Services](https://pscloud.uz/en) (`pscloud.uz`).**

The registry is **CCTLD.UZ**, operated by UZINFOCOM. It does not sell to end users; you buy
through one of its ~25 accredited registrars, and PS Cloud is one of them. It is also a
Tashkent cloud provider, so the domain and the server in §2 come from one vendor, on one
invoice, with one support contact — which matters more than saving a few dollars when
something breaks at 2am.

For `narxnoma.com`, use **[Cloudflare Registrar](https://www.cloudflare.com/products/registrar/)**
— wholesale cost, no renewal markup, no upsells. It cannot sell `.uz`, which is the only
reason the two domains come from different places.

> If PS Cloud turns out to be unavailable or the pricing is bad, the fallback is
> [aHOST](https://www.ahost.uz/en) — Tashkent-based since 2010 as SUVAN NET LLC, also both
> registrar and host. The full official registrar list is at <https://cctld.uz/reg/?lang=eng>.
> Tell me if you switch; nothing else in this document changes.

### Registration settings

- Register for **2 years minimum**. A one-year registration is a small negative SEO signal
  and creates an annual expiry risk on your main asset.
- Turn **auto-renew ON**.
- Turn **WHOIS privacy ON** if offered.
- Registrant details must be accurate — a false WHOIS is grounds for suspension.

### After purchase

Do **not** configure DNS at the registrar. We will point the domain at Cloudflare in §3, and
manage records there instead. All you need from the registrar panel is the ability to change
**nameservers**.

- [ ] `narxnoma.uz` registered, auto-renew on
- [ ] (optional) `narxnoma.com` registered
- [ ] You can log in to the registrar and reach the nameserver settings

---

## 2. Buy the server

### Specification

| Item | Value | Why |
|---|---|---|
| Location | **Tashkent, on TAS-IX** | Non-negotiable, see below |
| OS | **Ubuntu 24.04 LTS** | What every deployment step assumes |
| vCPU | 4 | Postgres + Next.js + a 7-source crawl |
| RAM | **8 GB** | Postgres wants 2–3 GB; Next.js build peaks near 2 GB |
| Disk | 80–160 GB NVMe/SSD | `raw_offer` is append-only and grows forever |
| IPv4 | 1 dedicated public address | Needed for DNS and TLS |
| Backups | Enable provider snapshots if offered | Cheapest insurance you will ever buy |

**Why Tashkent and TAS-IX specifically.** TAS-IX is Uzbekistan's internal peering exchange.
Traffic inside it is fast and cheap for local users, so your pages load quickly for the
people you are actually selling to. Just as important, the crawler will egress from an Uzbek
IP address — the retailer APIs we depend on are Uzbek services, and a foreign IP raises the
risk of throttling or blocking. We already have one live example: `ishonchsale.uz` returns
403 at the Cloudflare edge for our current egress IP.

A German host like Hetzner would be cheaper and technically excellent, but it gives up both
of those advantages. Not worth it here.

### Where to buy

**Buy it from [PS Cloud Services](https://pscloud.uz/en)** — the same vendor as the domain,
Tashkent datacenter, one invoice.

> Fallbacks if PS Cloud can't supply this spec: [aHOST VDS](https://www.ahost.uz/en/vds)
> (TAS-IX, long track record) or [UzCloud](https://uzcloud.uz/en/infrastructure/vm)
> (Tier III Tashkent, built around Uzbek data-residency compliance). Either is fine — just
> tell me which, and give me the IP.

### During setup

- Choose **Ubuntu 24.04 LTS**, not 22.04, not Debian, not a control-panel image.
- If the provider asks for an SSH public key during creation, use the one you generate in
  §4 — that saves a step. If it only offers a root password, that is fine too; we will
  switch to keys and disable password login immediately.
- Note the **public IPv4 address**.

- [ ] Server created, Ubuntu 24.04 LTS
- [ ] Public IPv4 address noted
- [ ] Snapshots/backups enabled

---

## 3. Create a Cloudflare account and point the domain at it

Cloudflare's free tier gives you DNS, TLS, caching, and DDoS protection. We use it
regardless of where the domain was bought.

1. Create a free account at <https://dash.cloudflare.com/sign-up>.
2. **Add a site** → enter `narxnoma.uz` → choose the **Free** plan.
3. Cloudflare shows you **two nameservers**, something like `xxx.ns.cloudflare.com`.
4. Go back to your registrar's panel and **replace the existing nameservers with those two**.
5. Wait for Cloudflare to report the domain as **Active** (usually under an hour, up to 24).

Do not add any DNS records yourself — I will create them.

- [ ] Cloudflare account created
- [ ] `narxnoma.uz` added to Cloudflare
- [ ] Registrar nameservers changed to Cloudflare's
- [ ] Cloudflare shows the domain **Active**

---

## 4. Hand over access — the three things I need

This is the only part where mistakes are costly. Follow it exactly.

### 4a. SSH key — you generate it, I never see the private half

Run this in **PowerShell** on your machine:

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\narxnoma_ed25519" -C "narxnoma-deploy" -N '""'
```

That writes two files. Now print the **public** half:

```powershell
Get-Content "$env:USERPROFILE\.ssh\narxnoma_ed25519.pub"
```

Copy that one line and paste it into your provider's panel under **SSH keys**, attached to
the server. It starts with `ssh-ed25519` and is safe to share — it is a lock, not a key.

**The file without `.pub` is the private key. It stays on your machine. Never open it, never
paste it anywhere, never send it to me.**

Now create an SSH config entry so I can connect by name:

```powershell
Add-Content "$env:USERPROFILE\.ssh\config" @"

Host narxnoma
    HostName YOUR.SERVER.IP.HERE
    User root
    IdentityFile ~/.ssh/narxnoma_ed25519
    StrictHostKeyChecking accept-new
"@
```

Replace `YOUR.SERVER.IP.HERE` with the address from §2. Then verify it works:

```powershell
ssh narxnoma "echo connected && cat /etc/os-release | head -2"
```

If that prints `connected` and `Ubuntu 24.04`, you are done with this step.

- [ ] Keypair generated
- [ ] Public key added to the server in the provider panel
- [ ] `~/.ssh/config` entry added with the real IP
- [ ] `ssh narxnoma "echo connected"` works

### 4b. Cloudflare API token — scoped, written to a file

1. Go to <https://dash.cloudflare.com/profile/api-tokens> → **Create Token**.
2. Use the **Edit zone DNS** template.
3. Under **Zone Resources**, select **Include → Specific zone → narxnoma.uz**.
4. Create the token and copy it.
5. Write it to a file **without pasting it into our chat**:

```powershell
$token = Read-Host "Paste the Cloudflare token" -AsSecureString
[Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($token)
) | Set-Content -NoNewline -Encoding utf8 "$env:USERPROFILE\.narxnoma\cloudflare.token"
```

(Create the folder first if needed: `New-Item -ItemType Directory "$env:USERPROFILE\.narxnoma"`)

This token can only edit DNS for this one domain. It cannot touch billing, other domains, or
your account settings. That limit is deliberate.

- [ ] Token created with **Edit zone DNS**, scoped to `narxnoma.uz` only
- [ ] Token saved to `%USERPROFILE%\.narxnoma\cloudflare.token`

### 4c. Tell me these three things in chat

Only these — nothing secret:

1. The **server's public IPv4 address**
2. The **domain** you registered (confirm it is `narxnoma.uz`)
3. An **email address** for Let's Encrypt expiry notices (a real mailbox you read)

---

## 5. What I will do once you have finished

No further input needed from you.

**Server hardening.** Create a non-root `deploy` user, move SSH to key-only authentication,
disable root login and password login, enable the firewall (22, 80, 443 only), turn on
unattended security updates, and install fail2ban.

**Runtime.** Install Docker and the Compose plugin, then bring up PostgreSQL 16 with a
generated password stored only in the server's environment file, apply the schema, and set
up nightly `pg_dump` backups with retention.

**Crawler.** Deploy `narxnoma-crawler`, install a systemd timer running the full sweep every
4 hours with sources staggered, and wire logging so a failing source is visible rather than
silent.

**Web.** Build and deploy the Next.js app, put Caddy in front of it for automatic Let's
Encrypt TLS and HTTP/2, and configure the reverse proxy.

**DNS.** Create the `A` records for the apex and `www`, enable Cloudflare proxying, and set
TLS mode to Full (strict).

**Verification.** Run a real harvest, confirm prices land inside the sanity fences, open
generated retailer links in a browser to confirm they resolve to the right product, and
report the coverage numbers per source.

---

## 6. Before the site goes public — still yours to decide

None of these block deployment; they block *launch*.

- **Legal pages.** Uzbek consumer sites need a privacy policy and a personal-data processing
  consent. Your competitor publishes both. I can draft them, but a lawyer should review, and
  they must name a real legal entity.
- **Company identity.** Which entity operates Narxnoma, and what appears in the site footer
  and WHOIS.
- **Monetization.** Right now outbound links go to retailers untagged. If you want affiliate
  or CPC deals, that changes how `/api/out/` is built — tell me before we have traffic worth
  measuring.
- **Analytics.** I would suggest self-hosted Plausible over Google Analytics: no cookie
  banner needed, and it runs on the same server. Your call.
- **Source relationships.** We use documented public JSON APIs politely, at a slower rate
  than a normal shopper browsing. Some retailers may still prefer a formal arrangement.
  Worth deciding whether you want to approach any of them proactively.

---

## Quick reference

| Thing | Where | Cost shape |
|---|---|---|
| `narxnoma.uz` | [PS Cloud](https://pscloud.uz/en) | annual |
| `narxnoma.com` | [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) | annual, at cost |
| VPS 4/8/80 Tashkent | [PS Cloud](https://pscloud.uz/en) | monthly |
| DNS, TLS, CDN | [Cloudflare](https://dash.cloudflare.com/sign-up) | free tier |
| TLS certificates | Let's Encrypt via Caddy | free |

Two purchases, one vendor, plus a free Cloudflare account.

I have deliberately not quoted prices — they change, and they differ by promotion and
billing period. Check the current rates when you buy.
