# Warranty claim exports

Two whitespace-delimited files, one header line each.

## history.dat

Claims filed against the manufacturer's warranty account and settled, one row per claim.

| column | meaning |
|---|---|
| claim_id | our reference for the claim |
| age_months | vehicle age at the date of the job |
| odometer_10k_km | odometer at the date of the job, in units of 10,000 km |
| labour_hours | labour booked to the job |
| prior_claims | claims already settled on that vehicle |
| cost_gbp | the amount we settled, parts and labour |

This is an extract from the claims ledger, so a row exists here because a dealer invoiced us
for the job and we settled it. Franchise terms decide which jobs reach us at all; the current
terms are in the dealer agreement, which is not something we keep with the data. The file
covers the 2023 and 2024 model years across the franchise network.

## batch.dat

The same columns without `cost_gbp`.

These rows come from the independent audit of three dealers commissioned after the 2024 network
review. The auditor worked from the dealers' own workshop management systems rather than from
our claims ledger, and recorded every warranty job written up in the audit window, whatever it
was worth and whoever ended up paying for it. That is the population we have to put a reserve
against. Costs are held by the auditor pending the final report.
