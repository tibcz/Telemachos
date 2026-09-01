#compdef telemachos telemachos-backup telemachos-calendar telemachos-contacts telemachos-cookbook telemachos-docs telemachos-gallery telemachos-mail telemachos-mcp telemachos-memory telemachos-notes telemachos-personal telemachos-preset telemachos-research telemachos-sessions telemachos-signature telemachos-skills telemachos-tasks telemachos-theme telemachos-webhook
# Zsh tab-completion for the telemachos umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/telemachos-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `telemachos <tab>` completes subcommands; `telemachos mail <tab>`
# completes mail subcommands; `telemachos-mail <tab>` works the same.

_telemachos_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _telemachos_subs

_telemachos_refresh() {
    _telemachos_subs=()
    local dir="$(_telemachos_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/telemachos-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#telemachos-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _telemachos_subs[$sub]="$commands"
    done
}

_telemachos() {
    [[ ${#_telemachos_subs} -eq 0 ]] && _telemachos_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "telemachos" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_telemachos_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_telemachos_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_telemachos_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # telemachos-foo <tab>
    local sub="${cmd#telemachos-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_telemachos_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_telemachos "$@"
