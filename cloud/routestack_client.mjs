import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import crypto from "node:crypto";

const API_KEY = process.env.ROUTESTACK_API_KEY || "rst_jWw6U4c796bpqAOJA82HsoxYroOT4yli";
const API_SECRET = process.env.ROUTESTACK_API_SECRET || "524655d09798585cc4f5a94c41e99660229c2f4f7c92af2d18c5fefb4c19aef8";
const MCP_URL = process.env.ROUTESTACK_MCP_URL || "https://mcp.routestack.ai/sse";

let cachedToken = null;

async function getPartnerToken() {
  if (cachedToken) return cachedToken;
  if (!API_SECRET) return API_KEY;

  const ts = Math.floor(Date.now() / 1000);
  const nonce = crypto.randomUUID();
  const hmac = crypto
    .createHmac("sha256", API_SECRET)
    .update(`${API_KEY}:${ts}:${nonce}`)
    .digest("base64url");

  const base = new URL(MCP_URL);
  const tokenUrl = new URL("/mcp/auth/partner-token", base.origin);

  try {
    const res = await fetch(tokenUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ apiKey: API_KEY, hmac, timestamp: ts, nonce }),
    });
    const text = await res.text();
    if (res.ok) {
      const data = JSON.parse(text);
      const token = data.token || data.accessToken || data.partnerToken || data.jwt;
      if (token && typeof token === "string") {
        cachedToken = token;
        return token;
      }
    }
  } catch (e) {
    // Fall back to direct API key
  }
  return API_KEY;
}

async function connectMcp() {
  const url = new URL(MCP_URL);
  const token = await getPartnerToken();
  const headers = { Authorization: `Bearer ${token}` };

  let client = new Client({ name: "routestack-runner", version: "1.0.0" });

  try {
    const transport = new StreamableHTTPClientTransport(url, {
      requestInit: { headers },
    });
    await client.connect(transport);
    return client;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const isTransportMismatch =
      message.includes("404") ||
      message.includes("405") ||
      message.includes("Not Found") ||
      message.includes("Method Not Allowed");

    if (!isTransportMismatch) throw err;

    await client.close().catch(() => {});
    client = new Client({ name: "routestack-runner", version: "1.0.0" });
    const sseTransport = new SSEClientTransport(url, {
      requestInit: { headers },
    });
    await client.connect(sseTransport);
    return client;
  }
}

// Global Hub Region Classifier
const REGIONAL_HUBS = {
  oceania_pacific: ["SYD", "MEL", "BNE", "PER", "ADL", "AKL", "CHC", "NAN", "PPT", "RAR", "NOU", "POM"],
  hawaii: ["HNL", "OGG", "KOA", "LIH"],
  na_west: ["LAX", "SFO", "SEA", "YVR", "PDX", "SAN", "OAK", "SJC", "LAS", "PHX", "SLC"],
  na_east_central: ["ORD", "DFW", "DEN", "IAH", "ATL", "JFK", "EWR", "BOS", "MIA", "YYZ", "YUL", "IAD"],
  east_asia: ["HKG", "TPE", "ICN", "NRT", "HND", "KIX", "PVG", "CAN", "PEK"],
  southeast_asia: ["SIN", "KUL", "BKK", "MNL", "CGK", "DPS", "SGN", "HAN"],
  middle_east: ["DXB", "DOH", "AUH", "MCT", "RUH", "JED", "IST", "AMM"],
  europe_west: ["LHR", "LGW", "CDG", "AMS", "FRA", "MUC", "MAD", "BCN", "FCO", "MXP", "ZRH", "BRU", "DUB"],
  europe_east: ["ATH", "BUD", "WAW", "PRG", "VIE", "OTP", "SOF", "LCA", "HEL"],
  latin_america: ["MEX", "BOG", "GRU", "GIG", "SCL", "LIM", "PTY", "EZE"]
};

function getAirportRegion(code) {
  const c = code.toUpperCase();
  for (const [region, airports] of Object.entries(REGIONAL_HUBS)) {
    if (airports.includes(c)) return region;
  }
  return "other";
}

/**
 * Dynamically resolves the best strategic forwarding hubs from Hub X toward the destination.
 */
export function getForwardingHubs(hubX, finalDest, origin) {
  const h = hubX.toUpperCase();
  const d = finalDest.toUpperCase();
  const o = origin.toUpperCase();
  const hRegion = getAirportRegion(h);
  const dRegion = getAirportRegion(d);

  const candidates = new Set();

  if (dRegion === "na_west" || dRegion === "na_east_central") {
    // Corridor heading toward North America
    if (hRegion === "oceania_pacific" || hRegion === "hawaii") {
      ["LAX", "SFO", "HNL", "YVR", "SEA", "OAK", "SAN"].forEach(c => candidates.add(c));
    } else if (hRegion === "east_asia" || hRegion === "southeast_asia") {
      ["HNL", "NRT", "ICN", "YVR", "SFO", "LAX", "SEA"].forEach(c => candidates.add(c));
    } else if (hRegion === "na_west" && dRegion === "na_east_central") {
      ["DEN", "ORD", "DFW", "IAH"].forEach(c => candidates.add(c));
    }
  } else if (dRegion === "europe_west" || dRegion === "europe_east") {
    // Corridor heading toward Europe
    if (hRegion === "southeast_asia" || hRegion === "oceania_pacific") {
      ["SIN", "BKK", "DXB", "DOH", "IST", "ATH", "FRA"].forEach(c => candidates.add(c));
    } else if (hRegion === "middle_east") {
      ["ATH", "BUD", "VIE", "MXP", "FRA", "CDG", "LHR"].forEach(c => candidates.add(c));
    } else if (hRegion === "na_east_central" || hRegion === "na_west") {
      ["BOS", "JFK", "EWR", "DUB", "LHR", "CDG"].forEach(c => candidates.add(c));
    }
  } else if (dRegion === "east_asia" || dRegion === "southeast_asia") {
    // Corridor heading toward Asia
    if (hRegion === "oceania_pacific") {
      ["DPS", "SIN", "KUL", "MNL", "HKG", "BKK"].forEach(c => candidates.add(c));
    } else if (hRegion === "na_west") {
      ["HNL", "NRT", "ICN", "TPE", "HKG"].forEach(c => candidates.add(c));
    }
  } else if (dRegion === "oceania_pacific") {
    // Corridor heading toward Oceania
    if (hRegion === "na_west" || hRegion === "hawaii") {
      ["HNL", "NAN", "AKL", "SYD"].forEach(c => candidates.add(c));
    } else if (hRegion === "southeast_asia") {
      ["DPS", "SIN", "KUL", "PER", "SYD"].forEach(c => candidates.add(c));
    }
  }

  // Default global mega-gateways
  if (candidates.size === 0) {
    ["LAX", "SFO", "SIN", "HKG", "NRT", "DXB", "DOH", "LHR", "FRA"].forEach(c => candidates.add(c));
  }

  // Exclude Hub X itself, final destination, and origin
  candidates.delete(h);
  candidates.delete(d);
  candidates.delete(o);

  return Array.from(candidates).slice(0, 3);
}

/**
 * Searches a single flight leg using an existing MCP client.
 */
async function searchSingleLeg(client, { origin, dest, departDate, returnDate, cabin = "Economy", adults = 1, currency = "AUD", maxResults = 5, fetchCheckoutLimit = 1 }) {
  const isRoundTrip = Boolean(returnDate && returnDate !== "One-Way");
  const filter = {
    origin: origin.toUpperCase(),
    destination: dest.toUpperCase(),
    departureDate: departDate,
    tripType: isRoundTrip ? "RoundTrip" : "OneWay",
    adults: Number(adults) || 1,
    cabin: cabin || "Economy",
    currency: currency || "AUD"
  };
  if (isRoundTrip) filter.returnDate = returnDate;

  try {
    const res = await client.callTool({
      name: "flight_search",
      arguments: { filter }
    });

    let rawJson = "{}";
    for (const c of res.content || []) {
      if (c.text) { rawJson = c.text; break; }
    }
    const searchData = JSON.parse(rawJson);
    const results = searchData.result || [];
    if (!results.length) return { origin: origin.toUpperCase(), dest: dest.toUpperCase(), results: [], best: null };

    const sorted = [...results].sort((a, b) => {
      const pA = Number(a.ourprice || a.totalFare || 999999);
      const pB = Number(b.ourprice || b.totalFare || 999999);
      return pA - pB;
    });

    const quoteCurrency = searchData.currency || "USD";
    let fxRate = 1.0;
    if (quoteCurrency === "USD" && currency === "AUD") fxRate = 1.55;
    else if (quoteCurrency === "AUD" && currency === "USD") fxRate = 0.65;

    const parsed = [];
    for (let i = 0; i < Math.min(sorted.length, maxResults); i++) {
      const r = sorted[i];
      const flights = r.flights || [];
      const airlines = Array.from(new Set(flights.map(f => f.airline).filter(Boolean))).join(", ") || "Multiple Airlines";
      const rawTotal = Number(r.ourprice || r.totalFare || 0);
      const rawBase = Number(r.baseFare || 0);
      const rawTaxes = Number(r.taxes || 0);
      const netFare = Math.round(rawTotal * fxRate * 100) / 100;
      const baseFare = Math.round(rawBase * fxRate * 100) / 100;
      const taxes = Math.round(rawTaxes * fxRate * 100) / 100;

      const firstFlight = flights[0] || {};
      const checkInBag = (firstFlight.checkInBaggage && firstFlight.checkInBaggage[0]?.value) || "1 Piece";
      const cabinBag = (firstFlight.cabinBaggage && firstFlight.cabinBaggage[0]?.value) || "Small Bag";
      const remainingSeats = firstFlight.remainingSeats || null;

      let checkoutUrl = null;
      if (i < fetchCheckoutLimit && r.fareSourceCode) {
        try {
          const coRes = await client.callTool({
            name: "flight_get_checkout_url",
            arguments: {
              fareSourceCode: r.fareSourceCode,
              flight: r,
              origin: origin.toUpperCase(),
              destination: dest.toUpperCase(),
              departureDate: departDate,
              returnDate: returnDate || undefined,
              adults: Number(adults) || 1,
              correlationId: searchData.correlationId,
              searchFilterObj: searchData.searchFilterObj
            }
          });
          for (const c of coRes.content || []) {
            if (c.text) {
              const coData = JSON.parse(c.text);
              if (coData.url) checkoutUrl = coData.url;
            }
          }
        } catch (e) {}
      }

      parsed.push({
        origin: origin.toUpperCase(),
        dest: dest.toUpperCase(),
        depart_date: departDate,
        return_date: returnDate || "One-Way",
        airlines,
        flight_codes: flights.map(f => `${f.flightCode}${f.flightNumber}`).join(", "),
        net_fare: netFare,
        base_fare: baseFare,
        taxes: taxes,
        currency,
        check_in_baggage: checkInBag,
        cabin_baggage: cabinBag,
        remaining_seats: remainingSeats,
        checkout_url: checkoutUrl,
        hops: flights.length,
        stops: r.stops,
      });
    }

    return {
      origin: origin.toUpperCase(),
      dest: dest.toUpperCase(),
      results: parsed,
      best: parsed[0] || null
    };
  } catch (err) {
    return { origin: origin.toUpperCase(), dest: dest.toUpperCase(), results: [], best: null, error: String(err) };
  }
}

/**
 * Executes the full Multi-Corridor & Forwarding-Hub Flight Discovery algorithm.
 */
export async function exploreCorridors({ origin, dest, departDate, returnDate, cabin = "Economy", adults = 1, currency = "AUD", candidateHubs = [] }) {
  const client = await connectMcp();

  // 1. Benchmark: Direct / Single-ticket search
  console.error(`[Step 0] Querying direct route ${origin} ➔ ${dest}...`);
  const directSearch = await searchSingleLeg(client, { origin, dest, departDate, returnDate, cabin, adults, currency, maxResults: 5, fetchCheckoutLimit: 2 });

  // 2. Determine Candidate Gateway Hubs for Origin
  let hubs = candidateHubs;
  if (!hubs || hubs.length === 0) {
    if (["SYD", "MEL", "BNE", "PER", "AKL"].includes(origin.toUpperCase())) {
      hubs = ["NAN", "LAX", "HNL", "SFO"];
    } else if (["LHR", "CDG", "FRA", "AMS"].includes(origin.toUpperCase())) {
      hubs = ["SIN", "DXB", "DOH", "JFK"];
    } else {
      hubs = ["SIN", "DXB", "LAX", "HNL"];
    }
  }

  // 3. Step 1 & 2: Discover Hubs connecting to Origin (Origin ➔ Hubs)
  console.error(`[Step 1 & 2] Querying Origin ➔ Candidate Hubs (${hubs.join(", ")})...`);
  const leg1Searches = [];
  for (const hub of hubs) {
    leg1Searches.push(searchSingleLeg(client, { origin, dest: hub, departDate, returnDate, cabin, adults, currency, maxResults: 3, fetchCheckoutLimit: 1 }));
  }
  const leg1Results = await Promise.all(leg1Searches);

  // Filter hubs that returned valid flights and sort by cheapest Leg 1 entry fare
  const validHubs = leg1Results
    .filter(r => r.best && r.best.net_fare > 0)
    .sort((a, b) => a.best.net_fare - b.best.net_fare);

  console.error(`[Step 2 Result] Cheapest entry hubs from ${origin}:`, validHubs.map(h => `${h.dest} (${currency} ${h.best.net_fare})`).join(", "));

  // 4. Step 3a: Query each Hub direct to Destination (Hub ➔ Destination)
  const topHubs = validHubs.slice(0, 3);
  console.error(`[Step 3a] Querying Direct Hub ➔ Destination (${topHubs.map(h => h.dest).join(", ")} ➔ ${dest})...`);

  const leg2DirectSearches = [];
  for (const h of topHubs) {
    leg2DirectSearches.push(searchSingleLeg(client, { origin: h.dest, dest, departDate, returnDate, cabin, adults, currency, maxResults: 3, fetchCheckoutLimit: 1 }));
  }
  const leg2DirectResults = await Promise.all(leg2DirectSearches);

  // 5. Step 3b: DYNAMIC FORWARDING HUB DISCOVERY FOR EVERY HUB X
  console.error(`[Step 3b] Discovering best forwarding destinations from each Hub X toward ${dest}...`);
  const forwardingHubMap = new Map(); // key: `${hubX}➔${forwardingHub}`
  const finalLegMap = new Map();      // key: `${forwardingHub}➔${dest}`

  const fwdLegSearches = [];
  const finalLegSearches = [];
  const checkedFinalHubs = new Set();
  const hubCorridorAnalysis = [];

  for (const h of topHubs) {
    const hubX = h.dest;
    const forwardingCandidates = getForwardingHubs(hubX, dest, origin);
    console.error(`  - Forwarding destinations to evaluate from Hub ${hubX}: ${forwardingCandidates.join(", ")}`);

    for (const fwdHub of forwardingCandidates) {
      fwdLegSearches.push(
        searchSingleLeg(client, { origin: hubX, dest: fwdHub, departDate, returnDate, cabin, adults, currency, maxResults: 2, fetchCheckoutLimit: 1 })
          .then(res => {
            if (res.best) forwardingHubMap.set(`${hubX}➔${fwdHub}`, res.best);
            return res;
          })
      );

      if (!checkedFinalHubs.has(fwdHub) && fwdHub !== dest.toUpperCase()) {
        checkedFinalHubs.add(fwdHub);
        finalLegSearches.push(
          searchSingleLeg(client, { origin: fwdHub, dest, departDate, returnDate, cabin, adults, currency, maxResults: 2, fetchCheckoutLimit: 1 })
            .then(res => {
              if (res.best) finalLegMap.set(`${fwdHub}➔${dest}`, res.best);
              return res;
            })
        );
      }
    }
  }

  // Execute forwarding and final leg searches in parallel
  await Promise.all([...fwdLegSearches, ...finalLegSearches]);

  // 6. Step 4: Compare possibilities and assemble combinations
  const combinations = [];

  // A. Add Direct / Unified Single Ticket Options
  for (const d of (directSearch.results || [])) {
    combinations.push({
      route_summary: `${origin} ➔ ${dest} (Single Ticket Unified GDS)`,
      deal_depart_date: departDate,
      deal_return_date: returnDate,
      hops: d.hops || 1,
      airlines: d.airlines,
      ticket_type: "Single Ticket (GDS Wholesale)",
      confidence_tier: "LIVE_VERIFIED",
      is_live_verified: true,
      currency,
      net_fare: d.net_fare,
      base_fare: d.base_fare || d.net_fare * 0.8,
      checked_bag_fee: 0,
      cheapest_engine: "RouteStack GDS",
      checkout_url: d.checkout_url,
      check_in_baggage: d.check_in_baggage,
      remaining_seats: d.remaining_seats,
      legs: [
        {
          direction: "Round-Trip",
          origin,
          dest,
          airline: d.airlines,
          net_fare: d.net_fare,
          checkout_url: d.checkout_url,
        }
      ],
      comparison_verdict: "Benchmark Single Ticket"
    });
  }

  // B. Assemble 2-Hop Hacker Splits: Origin ➔ Hub X ➔ Dest
  for (const h of topHubs) {
    const leg1 = h.best;
    const l2Match = leg2DirectResults.find(r => r.origin === h.dest && r.dest === dest);
    const leg2 = l2Match ? l2Match.best : null;

    let twoHopFare = null;
    if (leg1 && leg2) {
      twoHopFare = Math.round((leg1.net_fare + leg2.net_fare) * 100) / 100;
      combinations.push({
        route_summary: `${origin} ➔ ${h.dest} ➔ ${dest} (2-Ticket Hacker Split)`,
        deal_depart_date: departDate,
        deal_return_date: returnDate,
        hops: 2,
        airlines: `${leg1.airlines} + ${leg2.airlines}`,
        ticket_type: "Self-Transfer (Hacker Fare)",
        confidence_tier: "LIVE_VERIFIED",
        is_live_verified: true,
        currency,
        net_fare: twoHopFare,
        base_fare: twoHopFare,
        checked_bag_fee: 0,
        cheapest_engine: "RouteStack GDS Split Tickets",
        checkout_url: leg1.checkout_url || leg2.checkout_url,
        check_in_baggage: `${leg1.check_in_baggage} / ${leg2.check_in_baggage}`,
        remaining_seats: Math.min(leg1.remaining_seats || 9, leg2.remaining_seats || 9),
        legs: [
          {
            direction: "Leg 1 (Origin ➔ Hub)",
            origin,
            dest: h.dest,
            airline: leg1.airlines,
            net_fare: leg1.net_fare,
            checkout_url: leg1.checkout_url,
          },
          {
            direction: "Leg 2 (Hub ➔ Dest)",
            origin: h.dest,
            dest,
            airline: leg2.airlines,
            net_fare: leg2.net_fare,
            checkout_url: leg2.checkout_url,
          }
        ],
        hacker_cart_links: [
          {
            direction: "Outbound / Return Leg 1",
            origin,
            dest: h.dest,
            date: departDate,
            estimated_fare: leg1.net_fare,
            currency,
            checkout_url: leg1.checkout_url,
          },
          {
            direction: "Outbound / Return Leg 2",
            origin: h.dest,
            dest,
            date: departDate,
            estimated_fare: leg2.net_fare,
            currency,
            checkout_url: leg2.checkout_url,
          }
        ],
        comparison_verdict: `Hacker Split via ${h.dest}`
      });
    }

    // C. Dynamic 3-Hop Optimization via best forwarding destinations from Hub X
    const forwardingCandidates = getForwardingHubs(h.dest, dest, origin);
    let bestFwdHub = null;
    let lowest3HopFare = 999999;

    for (const fwdHub of forwardingCandidates) {
      const leg2Fwd = forwardingHubMap.get(`${h.dest}➔${fwdHub}`);
      const leg3Dest = finalLegMap.get(`${fwdHub}➔${dest}`);

      if (leg1 && leg2Fwd && leg3Dest) {
        const total3Hop = Math.round((leg1.net_fare + leg2Fwd.net_fare + leg3Dest.net_fare) * 100) / 100;
        if (total3Hop < lowest3HopFare) {
          lowest3HopFare = total3Hop;
          bestFwdHub = { hub: fwdHub, fare: leg2Fwd.net_fare, leg3Fare: leg3Dest.net_fare, total: total3Hop };
        }

        combinations.push({
          route_summary: `${origin} ➔ ${h.dest} ➔ ${fwdHub} ➔ ${dest} (3-Ticket Hacker Split)`,
          deal_depart_date: departDate,
          deal_return_date: returnDate,
          hops: 3,
          airlines: `${leg1.airlines} + ${leg2Fwd.airlines} + ${leg3Dest.airlines}`,
          ticket_type: "Self-Transfer (3-Hop Hacker Fare)",
          confidence_tier: "LIVE_VERIFIED",
          is_live_verified: true,
          currency,
          net_fare: total3Hop,
          base_fare: total3Hop,
          checked_bag_fee: 0,
          cheapest_engine: "RouteStack GDS 3-Ticket Split",
          checkout_url: leg1.checkout_url || leg2Fwd.checkout_url || leg3Dest.checkout_url,
          check_in_baggage: `${leg1.check_in_baggage} / ${leg2Fwd.check_in_baggage}`,
          remaining_seats: Math.min(leg1.remaining_seats || 9, leg2Fwd.remaining_seats || 9, leg3Dest.remaining_seats || 9),
          legs: [
            { direction: "Leg 1", origin, dest: h.dest, airline: leg1.airlines, net_fare: leg1.net_fare, checkout_url: leg1.checkout_url },
            { direction: "Leg 2", origin: h.dest, dest: fwdHub, airline: leg2Fwd.airlines, net_fare: leg2Fwd.net_fare, checkout_url: leg2Fwd.checkout_url },
            { direction: "Leg 3", origin: fwdHub, dest, airline: leg3Dest.airlines, net_fare: leg3Dest.net_fare, checkout_url: leg3Dest.checkout_url }
          ],
          hacker_cart_links: [
            { direction: "Leg 1", origin, dest: h.dest, date: departDate, estimated_fare: leg1.net_fare, currency, checkout_url: leg1.checkout_url },
            { direction: "Leg 2", origin: h.dest, dest: fwdHub, date: departDate, estimated_fare: leg2Fwd.net_fare, currency, checkout_url: leg2Fwd.checkout_url },
            { direction: "Leg 3", origin: fwdHub, dest, date: departDate, estimated_fare: leg3Dest.net_fare, currency, checkout_url: leg3Dest.checkout_url }
          ],
          comparison_verdict: `3-Hop Hacker Split via ${h.dest} & ${fwdHub}`
        });
      }
    }

    // Build the optimization record for this Hub X
    let optVerdict = "No onward flight found";
    if (twoHopFare && lowest3HopFare < 999999) {
      if (twoHopFare < lowest3HopFare) {
        optVerdict = `Direct from ${h.dest} (${currency} ${twoHopFare}) is ${currency} ${(lowest3HopFare - twoHopFare).toFixed(0)} CHEAPER than forwarding via ${bestFwdHub.hub} (${currency} ${lowest3HopFare})`;
      } else {
        optVerdict = `Forwarding via ${bestFwdHub.hub} (${currency} ${lowest3HopFare}) is ${currency} ${(twoHopFare - lowest3HopFare).toFixed(0)} CHEAPER than direct from ${h.dest} (${currency} ${twoHopFare})!`;
      }
    } else if (twoHopFare) {
      optVerdict = `Direct connection from ${h.dest} to ${dest} available (${currency} ${twoHopFare})`;
    }

    hubCorridorAnalysis.push({
      hub: h.dest,
      origin_to_hub_fare: leg1.net_fare,
      airlines: leg1.airlines,
      forwarding_candidates_tested: forwardingCandidates,
      best_forwarding_dest: bestFwdHub ? bestFwdHub.hub : "None",
      forwarding_fare: bestFwdHub ? bestFwdHub.fare : null,
      two_hop_total: twoHopFare,
      three_hop_total: lowest3HopFare < 999999 ? lowest3HopFare : null,
      optimization_verdict: optVerdict
    });
  }

  // Sort all combinations by net_fare
  combinations.sort((a, b) => a.net_fare - b.net_fare);

  await client.close().catch(() => {});

  return {
    origin,
    destination: dest,
    depart_date: departDate,
    return_date: returnDate,
    currency,
    benchmark_direct_fare: directSearch.best ? directSearch.best.net_fare : null,
    total_options_evaluated: combinations.length,
    combinations,
    corridors_analyzed: hubCorridorAnalysis
  };
}

export async function searchFlights({ origin, dest, departDate, returnDate, cabin = "Economy", adults = 1, currency = "AUD" }) {
  const client = await connectMcp();
  const res = await searchSingleLeg(client, { origin, dest, departDate, returnDate, cabin, adults, currency, maxResults: 10, fetchCheckoutLimit: 2 });
  await client.close().catch(() => {});
  return {
    count: res.results.length,
    results: res.results
  };
}

async function main() {
  const args = process.argv.slice(2);
  const getArg = (flag, def = "") => {
    const idx = args.indexOf(flag);
    return idx !== -1 && args[idx + 1] ? args[idx + 1] : def;
  };

  const mode = getArg("--mode", "single");
  const origin = getArg("--origin", "SYD");
  const dest = getArg("--dest", "SEA");
  const departDate = getArg("--depart", "2027-08-10");
  const returnDate = getArg("--return", "2027-08-25");
  const cabin = getArg("--cabin", "Economy");
  const adults = getArg("--adults", "1");
  const currency = getArg("--currency", "AUD");
  const hubsRaw = getArg("--hubs", "");
  const candidateHubs = hubsRaw ? hubsRaw.split(",").map(h => h.trim().toUpperCase()) : [];

  try {
    if (mode === "corridor") {
      const output = await exploreCorridors({ origin, dest, departDate, returnDate, cabin, adults, currency, candidateHubs });
      console.log(JSON.stringify(output, null, 2));
    } else {
      const output = await searchFlights({ origin, dest, departDate, returnDate, cabin, adults, currency });
      console.log(JSON.stringify(output, null, 2));
    }
  } catch (err) {
    console.error(JSON.stringify({ error: String(err) }));
    process.exit(1);
  }
}

if (process.argv[1] && process.argv[1].endsWith("routestack_client.mjs")) {
  main();
}
