""" rTorrent Control.

    Copyright (c) 2010, 2011 The PyroScope Project <pyroscope.project@gmail.com>
"""
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
import re
import sys
import time
import logging
import operator
from collections import defaultdict

from pyrobase.parts import Bunch, DefaultBunch
from pyrocore import config
from pyrocore.util import os, fmt, osmagic, matching
from pyrocore.scripts.base import ScriptBase, ScriptBaseWithConfig, PromptDecorator
from pyrocore.torrent import engine, formatting 


def print_help_fields():
    """ Print help about fields and field formatters.
    """
    # Mock entries, so they fulfill the expectations towards a field definition
    def custom_manifold():
        "named rTorrent custom attribute, e.g. 'custom_completion_target'"
        return ("custom_KEY", custom_manifold)
    def kind_manifold():
        "file types that contribute at least N% to the item's total size"
        return ("kind_N", kind_manifold)

    print('')
    print("Fields are:")
    print("\n".join(["  %-21s %s" % (name, field.__doc__)
        for name, field in sorted(engine.FieldDefinition.FIELDS.items() + [
            custom_manifold(), kind_manifold(),
        ])
    ]))

    print('')
    print("Format specifiers are:")
    print("\n".join(["  %-21s %s" % (name, doc)
        for name, doc in sorted(formatting.OutputMapping.formatter_help())
    ]))


class FieldStatistics(object):
    """ Collect statistical values for the fields of a search result.
    """
    
    def __init__(self, size):
        "Initialize accumulator"
        self.size = size
        self.errors = DefaultBunch(int)
        self.total = DefaultBunch(int)
        self.min = DefaultBunch(int)
        self.max = DefaultBunch(int)
        self._basetime = time.time()


    def __nonzero__(self):
        "Truth"
        return bool(self.total) 


    def add(self, field, val):
        "Add a sample"
        if engine.FieldDefinition.FIELDS[field]._matcher is matching.TimeFilter:
            val = self._basetime - val

        try:
            self.total[field] += val
            self.min[field] = min(self.min[field], val) if field in self.min else val
            self.max[field] = max(self.max[field], val)
        except (ValueError, TypeError):
            self.errors[field] += 1


    @property
    def average(self):
        "Calculate average"
        result = DefaultBunch(str)

        # Calculate average if possible
        if self.size:
            result.update(
                (key, '' if isinstance(val, basestring) else val / self.size)
                for key, val in self.total.items()
            )

        # Handle time fields
        #for key, fielddef in  engine.FieldDefinition.FIELDS.items():
        #    if key in result and fielddef._matcher is matching.TimeFilter:
        #       result[key] = ''
        #for key, fielddef in  engine.FieldDefinition.FIELDS.items():
        #    if key in result and fielddef._matcher is matching.TimeFilter:
        #        result[key] = engine._fmt_duration(result[key])
        #print self.total
        #print result
        return result
        

class RtorrentControl(ScriptBaseWithConfig):
    ### Keep things wrapped to fit under this comment... ##############################
    """ 
        Control and inspect rTorrent from the command line.
    
        Filter expressions take the form "<field>=<value>", and all expressions must
        be met (AND). If a field name is omitted, "name" is assumed. You can also use
        uppercase OR to build a list of alternative conditions.
        
        For numeric fields, a leading "+" means greater than, a leading "-" means less 
        than. For string fields, the value is a glob pattern (*, ?, [a-z], [!a-z]).
        Multiple values separated by a comma indicate several possible choices (OR).
        "!" in front of a filter value negates it (NOT).
        
        Examples:
          - All 1:1 seeds         ratio=+1
          - All active torrents   xfer=+0
          - All seeding torrents  up=+0
          - Slow torrents         down=+0 down=-5k
          - Older than 2 weeks    completed=+2w
          - Big stuff             size=+4g
          - 1:1 seeds not on NAS  ratio=+1 'realpath=!/mnt/*'
          - Music                 kind=flac,mp3
    """

    # argument description for the usage information
    ARGS_HELP = "<filter>..."

    # additonal stuff appended after the command handler's docstring
    ADDITIONAL_HELP = ["", "", "Use --help-fields to list all fields and their description."]

    # additional values for output formatting
    FORMATTER_DEFAULTS = dict(
        now = time.time(),
    )

    # choices for --ignore
    IGNORE_OPTIONS = ('0', '1')

    # action options that perform some change on selected items
    ACTION_MODES = ( 
        Bunch(name="start", options=("--start",), help="start torrent"), 
        Bunch(name="close", options=("--close", "--stop"), help="stop torrent", method="stop"), 
        Bunch(name="hash_check", label="HASH", options=("-H", "--hash-check"), help="hash-check torrent", interactive=True), 
        # TODO: Bunch(name="announce", options=("--announce",), help="announce right now", interactive=True), 
        # TODO: --pause, --resume?
        # TODO: implement --clean-partial
        #self.add_bool_option("--clean-partial",
        #    help="remove partially downloaded 'off'ed files (also stops downloads)")
        Bunch(name="delete", options=("--delete",), help="remove torrent from client", interactive=True), 
        Bunch(name="purge", options=("--purge", "--delete-partial"), 
              help="delete PARTIAL data files and remove torrent from client", interactive=True), 
        Bunch(name="cull", options=("--cull", "--exterminate", "--delete-all"), 
            help="delete ALL data files and remove torrent from client", interactive=True), 
        Bunch(name="throttle", options=("-T", "--throttle",), argshelp="NAME", method="set_throttle",
            help="assign to named throttle group (NULL=unlimited, NONE=global)", interactive=True), 
        Bunch(name="tag", options=("--tag",), argshelp='"TAG +TAG -TAG..."',
            help="add or remove tag(s)", interactive=False), 
        Bunch(name="custom", label="SET_CUSTOM", options=("--custom",), argshelp='KEY=VALUE', method="set_custom",
            help="set value of 'custom_KEY' field (KEY might also be 1..5)", interactive=False), 
        # TODO: --with-dupes / -D Include any items that reference the same data paths as the selected ones
        # TODO: --no-dupes / --unique / -U Exclude any items that reference the same data paths as any other (from deletion, etc.)
        # TODO: --move / --link output_format / the formatted result is the target path
        #           if the target contains a '//' in place of a '/', directories
        #           after that are auto-created
        #           "--move tracker_dated", with a custom output format 
        #           like "tracker_dated = ~/done//$(alias)s/$(completed).7s",
        #           will move to ~/done/OBT/2010-08 for example
        #        self.add_value_option("--move", "TARGET",
        #            help="move data to given target directory (implies -i, can be combined with --delete)")
        # TODO: --copy, and --move/--link across devices
        # TODO:
        # Bunch(name="xmlrpc", options=("--xmlrpc",), argshelp="CMD[,ARG1,...]", method="xmlrpc",
        #     help="call raw XMLRPC command", interactive=True), 
    )


    def __init__(self):
        """ Initialize rtcontrol.
        """
        super(RtorrentControl, self).__init__()

        self.prompt = PromptDecorator(self)
        self.plain_output_format = False


    def add_options(self):
        """ Add program options.
        """
        super(RtorrentControl, self).add_options()

        # basic options
        self.add_bool_option("--help-fields",
            help="show available fields and their description")
        self.add_bool_option("-n", "--dry-run",
            help="don't commit changes, just tell what would happen")
        self.add_bool_option("--detach",
            help="run the process in the background")
        self.prompt.add_options()
      
        # output control
        self.add_bool_option("-S", "--shell",
            help="escape output following shell rules")
        self.add_bool_option("-0", "--nul", "--print0",
            help="use a NUL character instead of a linebreak after items")
        self.add_bool_option("-c", "--column-headers",
            help="print column headers")
        self.add_bool_option("-+", "--stats",
            help="add sum / avg / median of numerical fields")
        self.add_bool_option("--summary",
            help="print only statistical summary, without the items")
        #self.add_bool_option("-f", "--full",
        #    help="print full torrent details")
        self.add_value_option("-o", "--output-format", "FORMAT",
            help="specify display format (use '-o-' to disable item display)")
        self.add_value_option("-O", "--output-template", "FILE",
            help="pass control of output formatting to the specified template")
        self.add_value_option("-s", "--sort-fields", "[-]FIELD[,...]",
            help="fields used for sorting, descending if prefixed with a '-'; '-s*' uses output field list")
        self.add_bool_option("-r", "--reverse-sort",
            help="reverse the sort order")
        self.add_bool_option("-V", "--view-only",
            help="show search result only in default ncurses view")
        self.add_value_option("--to-view", "NAME",
            help="show search result only in named ncurses view")
        self.add_bool_option("--tee-view",
            help="ADDITIONALLY show search results in ncurses view (modifies -V and --to-view behaviour)")
        self.add_value_option("--from-view", "NAME",
            help="select only items that are on view NAME")
# TODO: implement -S
#        self.add_bool_option("-S", "--summary",
#            help="print statistics")

        # torrent state change (actions)
        for action in self.ACTION_MODES:
            action.setdefault("label", action.name.upper())
            action.setdefault("method", action.name)
            action.setdefault("interactive", False)
            action.setdefault("argshelp", "")
            action.setdefault("args", ())
            if action.argshelp:
                self.add_value_option(*action.options + (action.argshelp,), 
                    **{"help": action.help + (" (implies -i)" if action.interactive else "")})
            else:
                self.add_bool_option(*action.options, 
                    **{"help": action.help + (" (implies -i)" if action.interactive else "")})
        self.add_value_option("--ignore", "|".join(self.IGNORE_OPTIONS),
            type="choice", choices=self.IGNORE_OPTIONS,
            help="set 'ignore commands' status on torrent")
        self.add_bool_option("-F", "--flush", help="flush changes immediately (save session data)")


    def help_completion_fields(self):
        """ Return valid field names.
        """
        for name, field in sorted(engine.FieldDefinition.FIELDS.items()):
            if issubclass(field._matcher, matching.BoolFilter):
                yield "%s=no" % (name,)
                yield "%s=yes" % (name,)
                continue
            elif issubclass(field._matcher, matching.PatternFilter):
                yield "%s=" % (name,)
                yield "%s=/" % (name,)
                yield "%s=?" % (name,)
                yield "%s=\"'*'\"" % (name,)
                continue
            elif issubclass(field._matcher, matching.NumericFilterBase):
                for i in range(10):
                    yield "%s=%d" % (name, i)
            else:
                yield "%s=" % (name,)

            yield r"%s=+" % (name,)
            yield r"%s=-" % (name,)
                
        yield "custom_"
        yield "kind_"


    # TODO: refactor to engine.TorrentProxy as format() method
    def format_item(self, item, defaults=None, stencil=None):
        """ Format an item.
        """
        try:
            item_text = fmt.to_console(formatting.format_item(self.options.output_format, item, defaults)) 
        except (NameError, ValueError, TypeError), exc:
            self.fatal("Trouble with formatting item %r\n\n  FORMAT = %r\n\n  REASON =" % (item, self.options.output_format), exc)
            raise # in --debug mode

        # Escape for shell use?
        def shell_escape(text):
            "Escape helper"
            return text if text.isalnum() else "'%s'" % text.replace("'", r"'\''")

        if self.options.shell:
            item_text = '\t'.join(shell_escape(i) for i in item_text.split('\t'))

        # Justify headers according to stencil
        if stencil:
            item_text = '\t'.join(i.ljust(len(s)) for i, s in zip(item_text.split('\t'), stencil))

        return item_text


    def emit(self, item, defaults=None, stencil=None, to_log=False, item_formatter=None):
        """ Print an item to stdout, or the log on INFO level.
        """
        item_text = self.format_item(item, defaults, stencil)

        # Post-process line?
        if item_formatter: 
            item_text = item_formatter(item_text)

        # For a header, use configured escape codes on a terminal
        if item is None and os.isatty(sys.stdout.fileno()):
            item_text = ''.join((config.output_header_ecma48, item_text, "\x1B[0m"))

        # Dump to selected target
        if to_log:
            self.LOG.info(item_text)
        elif self.options.nul:
            sys.stdout.write(item_text + '\0')
            sys.stdout.flush()
        else: 
            print(item_text)

        return item_text.count('\n') + 1


    # TODO: refactor to formatting.OutputMapping as a class method
    def validate_output_format(self, default_format):
        """ Prepare output format for later use.
        """
        output_format = self.options.output_format

        # Use default format if none is given
        if output_format is None:
            output_format = default_format

        # Check if it's a custom output format from configuration
        # (they take precedence over field names, so name them wisely)
        output_format = config.formats.get(output_format, output_format)

        # Expand plain field list to usable form
        if re.match(r"^[,._0-9a-zA-Z]+$", output_format):
            self.plain_output_format = True
            output_format = "%%(%s)s" % ")s\t%(".join(formatting.validate_field_list(output_format, allow_fmt_specs=True))

        # Replace some escape sequences
        output_format = (output_format
            .replace(r"\\", "\\")
            .replace(r"\n", "\n")
            .replace(r"\t", "\t")
            .replace(r"\$", "\0") # the next 3 allow using $() instead of %()
            .replace("$(", "%(")
            .replace("\0", "$")
            .replace(r"\ ", " ") # to prevent stripping in config file
            #.replace(r"\", "\")
        )                            

        self.options.output_format = formatting.preparse(output_format)


    # TODO: refactor to engine.FieldDefinition as a class method
    def get_output_fields(self):
        """ Get field names from output template.
        """
        # Re-engineer list from output format
        # XXX TODO: Would be better to use a FieldRecorder class to catch the full field names 
        emit_fields = list(i.lower() for i in re.sub(r"[^_A-Z]+", ' ', self.format_item(None)).split())

        # Validate result
        result = []
        for name in emit_fields[:]:
            if name not in engine.FieldDefinition.FIELDS:
                self.LOG.warn("Omitted unknown name '%s' from statistics and output format sorting" % name)
            else:
                result.append(name)
            
        return result


    def validate_sort_fields(self):
        """ Take care of sorting.
        """
        sort_fields = self.options.sort_fields
        if sort_fields == '*':
            sort_fields = self.get_output_fields()

        # Use default order if none is given
        if not sort_fields:
            sort_fields = config.sort_fields

        # Allow descending order per field by prefixing with '-'
        descending = defaultdict(bool)
        def sort_order_filter(name):
            "Helper to remove flag and memoize sort order"
            if name.startswith('-'):
                name = name[1:]
                descending[name] = True
            return name

        # Split and validate field list
        sort_fields = formatting.validate_field_list(sort_fields, name_filter=sort_order_filter)

        # No descending fields?
        if not any(descending.values()):
            self.LOG.debug("Sorting order is: %s" % ", ".join(sort_fields))
            return operator.attrgetter(*tuple(sort_fields))

        # Need to provide complex key
        class Key(object):
            "Complex sort order key"
            def __init__(self, obj, *args):
                "Remember object to be compared"
                self.obj = obj
            def __lt__(self, other):
                "Compare to other key"
                for field in sort_fields:
                    a, b = getattr(self.obj, field), getattr(other.obj, field)
                    #print descending[field], field, a, b
                    if a == b:
                        continue
                    return b < a if descending[field] else a < b
                return False

        return Key


    def show_in_view(self, sourceview, matches, targetname=None):
        """ Show search result in ncurses view.
        """
        targetname = targetname or self.options.to_view or "rtcontrol"
        config.engine.show(matches, targetname)
        msg = "Filtered %d out of %d torrents using [ %s ]" % (
            len(matches), sourceview.size(), sourceview.matcher)
        self.LOG.info("%s into rTorrent view %r." % (msg, targetname))
        config.engine.log(msg)


    def mainloop(self):
        """ The main loop.
        """
        # Print field definitions?
        if self.options.help_fields:
            self.parser.print_help()
            print_help_fields()
            sys.exit(1)

        # Print usage if no conditions are provided
        if not self.args:
            self.parser.error("No filter conditions given!")

        # Check special action options
        action = None
        if self.options.ignore:
            action = Bunch(name="ignore", method="ignore", label="IGNORE" if int(self.options.ignore) else "HEED", 
                help="commands on torrent", interactive=False, args=(self.options.ignore,))

        # Check standard action options
        # TODO: Allow certain combinations of actions (like --tag foo --stop etc.)
        #       How do we get a sensible order of execution?
        for action_mode in self.ACTION_MODES:
            if getattr(self.options, action_mode.name):
                if action:
                    self.parser.error("Options --%s and --%s are mutually exclusive" % (
                        action.name.replace('_', '-'), action_mode.name.replace('_', '-'),
                    ))
                action = action_mode
                if action.argshelp:
                    action.args = (getattr(self.options, action.name),)
        if not action and self.options.flush:
            action = Bunch(name="flush", method="flush", label="FLUSH", 
                help="flush session data", interactive=False, args=())
            self.options.flush = False # No need to flush twice
        if action and action.interactive:
            self.options.interactive = True

#        print repr(config.engine)
#        config.engine.open()
#        print repr(config.engine)

        # Preparation steps
        default_output_format = "default"
        if action:
            default_output_format = "action_cron" if self.options.cron else "action"
        self.validate_output_format(default_output_format)
        sort_key = self.validate_sort_fields()
        matcher = matching.ConditionParser(engine.FieldDefinition.lookup, "name").parse(self.args)
        self.LOG.debug("Matcher is: %s" % matcher)

        # Detach to background?
        # This MUST happen before the next step, when we connect to the torrent client
        if self.options.detach:
            config.engine.load_config()
            osmagic.daemonize(logfile=config.log_execute)
            time.sleep(.05) # let things settle a little

        # Find matching torrents
        # TODO: this could get speedier quite a bit when we pre-select
        # a subset of all items in rtorrent itself, via a dynamic view!
        # Or sort them just the right way, and then abort after we cannot
        # possibly find more matches.
        #
        view = config.engine.view(self.options.from_view, matcher)
        matches = list(view.items())
        matches.sort(key=sort_key, reverse=self.options.reverse_sort)

        if not matches:
            # Think "404 NOT FOUND", but then exit codes should be < 256
            self.return_code = 44

        # Build header stencil
        stencil = None
        if self.options.column_headers and self.plain_output_format and matches:
            stencil = fmt.to_console(formatting.format_item(
                self.options.output_format, matches[0], self.FORMATTER_DEFAULTS)).split('\t')

        # Tee to ncurses view, if requested
        if self.options.tee_view and (self.options.to_view or self.options.view_only):
            self.show_in_view(view, matches)

        # Generate summary?
        summary = FieldStatistics(len(matches))
        if self.options.stats or self.options.summary:
            for field in self.get_output_fields():
                try:
                    0 + getattr(matches[0], field)
                except (TypeError, ValueError, IndexError):
                    summary.total[field] = ''
                else:
                    for item in matches:
                        summary.add(field, getattr(item, field))

        # Execute action?
        if action:
            self.LOG.log(logging.DEBUG if self.options.cron else logging.INFO, "%s %s %d out of %d torrents." % (
                "Would" if self.options.dry_run else "About to", action.label, len(matches), view.size(),
            ))
            defaults = {"action": action.label}
            defaults.update(self.FORMATTER_DEFAULTS)

            if self.options.column_headers and matches:
                self.emit(None, stencil=stencil)

            # Perform chosen action on matches
            for item in matches:
                if not self.prompt.ask_bool("%s item %s" % (action.label, item.name)):
                    continue
                if self.options.output_format and self.options.output_format != "-":
                    self.emit(item, defaults, to_log=self.options.cron)
                if not self.options.dry_run:
                    getattr(item, action.method)(*action.args)
                    if self.options.flush:
                        item.flush()

        # Show in ncurses?
        elif not self.options.tee_view and (self.options.to_view or self.options.view_only):
            self.show_in_view(view, matches)

        # Show via template?
        elif self.options.output_template:
            output_template = self.options.output_template
            if not output_template.startswith("file:"):
                output_template = "file:" + output_template

            sys.stdout.write(formatting.expand_template(output_template, dict(
                version = self.version, 
                proxy = config.engine.open(),
                view = view, 
                query = matcher, 
                matches = matches, 
                summary = summary
            )))
            sys.stdout.flush()

        # Show on console?
        elif self.options.output_format and self.options.output_format != "-":
            if not self.options.summary:
                line_count = 0
                for item in matches:
                    # Emit a header line every 'output_header_frequency' lines
                    if self.options.column_headers and line_count % config.output_header_frequency == 0:
                        self.emit(None, stencil=stencil)
    
                    # Print matching item
                    line_count += self.emit(item, self.FORMATTER_DEFAULTS)

            # Print summary?
            if matches and summary:
                self.emit(None, stencil=stencil, 
                    #item_formatter=None if self.options.summary
                    #    # TODO: this can be done better! 
                    #    else lambda i: re.sub("[^ \t]", "=", i)
                    #    #else lambda i: re.sub("=[ \t]+", lambda k: "=" * len(k.group(0)) + k.group(0)[-1], re.sub("[^ \t]", "=", i))
                )
                self.emit(summary.total, item_formatter=lambda i: i.rstrip() + " [SUM of %d item(s)]" % len(matches))
                self.emit(summary.min, item_formatter=lambda i: i.rstrip() + " [MIN of %d item(s)]" % len(matches))
                self.emit(summary.average, item_formatter=lambda i: i.rstrip() + " [AVG of %d item(s)]" % len(matches))
                self.emit(summary.max, item_formatter=lambda i: i.rstrip() + " [MAX of %d item(s)]" % len(matches))
                
            self.LOG.info("Dumped %d out of %d torrents." % (len(matches), view.size(),))
        else:
            self.LOG.info("Filtered %d out of %d torrents." % (len(matches), view.size(),))
        
        if self.options.debug and 0:
            print '\n' + repr(matches[0])
            print '\n' + repr(matches[0].files)
        
        # XMLRPC stats
        self.LOG.debug("XMLRPC stats: %s" % config.engine._rpc)


def run(): #pragma: no cover
    """ The entry point.
    """
    ScriptBase.setup()
    RtorrentControl().run()


if __name__ == "__main__":
    run()

