select *
from read_json_auto(
  '{{ var("attempts_path") }}',
  format = 'newline_delimited'
)
