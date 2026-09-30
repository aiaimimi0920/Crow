#!/usr/bin/env bash
# Pure alias helpers. Caller controls defaults and any runtime side effects.
crow_env_names() {
  local name="$1"
  [[ "$name" =~ ^(CROW|FAPAI)_[A-Z0-9_]+$ ]] || { echo 'Invalid Crow environment key' >&2; return 2; }
  _crow_alias_new="CROW_${name#*_}"
  _crow_alias_old="FAPAI_${name#*_}"
}

crow_lexical_path() {
  local value="$1" prefix='/' part result
  local -a pieces=() normalized=()
  [[ "$value" != *$'\n'* ]] || return 2
  [[ "$value" == /* ]] || value="$PWD/$value"
  [[ "$value" == //* && "$value" != ///* ]] && prefix='//'
  IFS='/' read -r -a pieces <<< "$value"
  for part in "${pieces[@]}"; do
    case "$part" in
      ''|.) ;;
      ..) if ((${#normalized[@]})); then unset 'normalized[${#normalized[@]}-1]'; fi ;;
      *) normalized+=("$part") ;;
    esac
  done
  result="$prefix"
  for part in "${normalized[@]}"; do result="${result%/}/$part"; done
  printf '%s' "$result"
}

crow_env_pair_value() {
  local name="$1" new old first second
  crow_env_names "$name" || return
  new="$_crow_alias_new"; old="$_crow_alias_old"
  if [[ -v "$new" && -v "$old" && "${!new}" != "${!old}" ]]; then
    case "$new" in
      *_ROOT|*_ROOT_HOST|*_PATH|*_FILE|*_DIR|*_SNAPSHOT)
        first="$(crow_lexical_path "${!new}")" || return
        second="$(crow_lexical_path "${!old}")" || return
        [[ -n "${!new}" && -n "${!old}" && "$first" == "$second" ]] || {
          printf 'Conflicting environment aliases: %s, %s\n' "$new" "$old" >&2; return 2;
        } ;;
      *) printf 'Conflicting environment aliases: %s, %s\n' "$new" "$old" >&2; return 2 ;;
    esac
  fi
  if [[ -v "$new" ]]; then printf '%s' "${!new}"; else printf '%s' "${!old-}"; fi
}

crow_env() {
  local value
  value="$(crow_env_pair_value "$1")" || return
  printf '%s' "${value:-${2-}}"
}

crow_set_env() {
  local name="$1" value="$2" new old
  crow_env_names "$name" || return
  new="$_crow_alias_new"; old="$_crow_alias_old"
  printf -v "$new" '%s' "$value"
  printf -v "$old" '%s' "$value"
  export "$new" "$old"
}

crow_source_env_file() {
  local _crow_file="$1" _crow_validator="$2" _crow_options="$-" _crow_wire_mode="${3-}" _crow_names _crow_key _crow_new _crow_old _crow_value
  local -A _crow_declared=() _crow_prepared=()
  if [[ -n "$_crow_wire_mode" ]]; then
    _crow_names="$(python3 "$_crow_validator" "$_crow_file" "$_crow_wire_mode")" || return
  else
    _crow_names="$(python3 "$_crow_validator" "$_crow_file")" || return
  fi
  while IFS= read -r _crow_key; do
    [[ -n "$_crow_key" ]] || continue
    crow_env_names "$_crow_key" || return
    _crow_new="$_crow_alias_new"
    if [[ "$_crow_key" == CROW_* ]]; then
      _crow_declared["$_crow_new"]=$(( ${_crow_declared[$_crow_new]:-0} | 1 ))
    else
      _crow_declared["$_crow_new"]=$(( ${_crow_declared[$_crow_new]:-0} | 2 ))
    fi
  done <<< "$_crow_names"
  # Only the validated declaration subset is sourced, exactly once.
  set -a
  source "$_crow_file" || { [[ "$_crow_options" == *a* ]] || set +a; return 2; }
  [[ "$_crow_options" == *a* ]] || set +a
  for _crow_key in $(compgen -A variable CROW_; compgen -A variable FAPAI_); do
    crow_env_names "$_crow_key" || return
    _crow_new="$_crow_alias_new"; _crow_old="$_crow_alias_old"
    case "${_crow_declared[$_crow_new]:-0}" in
      1) _crow_value="${!_crow_new-}" ;;
      2) _crow_value="${!_crow_old-}" ;;
      *) _crow_value="$(crow_env_pair_value "$_crow_new")" || return ;;
    esac
    _crow_prepared["$_crow_new"]="$_crow_value"
  done
  for _crow_key in "${!_crow_prepared[@]}"; do crow_set_env "$_crow_key" "${_crow_prepared[$_crow_key]}"; done
}

crow_validate_env() {
  local name
  for name in $(compgen -A variable CROW_; compgen -A variable FAPAI_); do
    crow_env_pair_value "$name" >/dev/null || return
  done
}

crow_sync_env() {
  local name canonical value
  local -A prepared=()
  for name in $(compgen -A variable CROW_; compgen -A variable FAPAI_); do
    crow_env_names "$name" || return
    canonical="$_crow_alias_new"
    value="$(crow_env_pair_value "$canonical")" || return
    prepared["$canonical"]="$value"
  done
  for name in "${!prepared[@]}"; do crow_set_env "$name" "${prepared[$name]}"; done
}
