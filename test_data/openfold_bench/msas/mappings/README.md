# Mapping files
These files contain mappings between the following entities:
  query_name: name of the query complex in the input query cache
  chain_id: a (query_name, chain identifier) tuple, indicating a unique instantiation of a protein chain.
  rep_id: a chain_id associated with a unique protein sequence, selected upon first occurrence of that specific sequence; all subsequent chain_ids with the same sequence will have this chain_id as the representative
  seq: the actual protein sequence
  complex_id: an identifier associated with a unique SET of protein sequences in the same query, consisting of the sorted representative IDs of ALL chains in the complex; only used for queries with more than 2 unique protein sequences
