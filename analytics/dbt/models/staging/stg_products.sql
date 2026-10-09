select *
from read_json_auto(
  '{{ var("products_path") }}',
  format = 'newline_delimited'
)
