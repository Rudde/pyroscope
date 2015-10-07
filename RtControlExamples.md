See also RtXmlRpcExamples.

_Contents_ 

# Fundamentals #
`rtcontrol`'s main purpose is to take filter conditions on the command line of the form "_field_`=`_value_" and select a set of torrents according to them — and then either print the result according to a specified format to the console, add the selected items into their own rTorrent view for further inspection, or take some action on them.

All given conditions must be met (AND), and if a field name is omitted, "`name`" is assumed. Multiple values separated by a comma indicate several possible choices (OR). "`!`" in front of a filter value negates it (NOT). Use uppercase `OR` to combine multiple alternative sets of conditions. And finally brackets can be used to group conditions and alter the default "AND before OR" behaviour; be sure to separate both the opening and closing bracket by white space from surrounding text.

For string fields, the value is a [glob pattern](http://docs.python.org/library/fnmatch.html) which you are used to from shell filename patterns (`*`, `?`, `[a-z]`, `[!a-z]`); glob patterns must match the whole field value, i.e. use `*...*` for 'contains' type searches. To use [regex matches](http://docs.python.org/howto/regex.html) instead of globbing, enclose the pattern in slashes (`/regex/`). Since regex can express anchoring the match at the head (`^`) or tail (`$`), they're by default of the 'contains' type.

For numeric fields, a leading "`+`" means greater than, a leading "`-`" means less than (just like with the standard `find` command).

Selection on fields that are lists of tags or names (e.g. `tagged` and `views`) works by just providing the tags you want to search for. The difference to the glob patterns for string fields is that tagged search respects word boundaries (whitespace), and to get a match the given tag just has to appear anywhere in the list (`bar` matches on `foo bar baz`).

In time filtering conditions (e.g. for the `completed` and `loaded` fields), you have three possible options to specify the value:
  1. time deltas in the form "`<number><unit>...`", where unit is a single upper- or lower-case letter and one of `Y`ear, `M`onth, `W`eek, `D`ay, `H`our, m`I`nute, or `S`econd. The order is important (`y` before `m`), and a `+` before the delta means _older than_, while `-` means _younger than_. Example: `-1m2w3d`.
  1. a certain date and time in human readable form, where the date can be given in ISO (`Y-M-D`), American (`M/D/Y`), or European (`D.M.Y`) format. A date can be followed by a time, with minutes and seconds optional and separated by `:`. Put either a space or a `T` between the date and the time. Example: `+2010-08-15t14:50`.
  1. absolute numerical UNIX timestamp, i.e. what `ls -l --time-style '+%s'` returns. Example: `+1281876597`.


# Useful filter conditions #
The following conditions give you a hint on what you can do, and some building blocks for more complex conditions.

| **Condition(s)**     | **Description** |
|:---------------------|:----------------|
| `*HDTV*`             | Anything with "HDTV" in its name|
| `/s\d+e\d+/`         | Anything with typical TV episode numbering in its name (regex match) |
| `ratio=+1`           | All downloads seeded to at least 1:1 |
| `xfer=+0`            | All active torrents (transferring data) |
| `up=+0`              | All seeding torrents (uploading data) |
| `down=+0 down=-5k`   | Slow torrents (downloading, but with < 5 KB/s) |
| `down=0 is_complete=no is_open=yes` | Stuck torrents  |
| `size=+4g`           | Big stuff (DVD size or larger) |
| `is_complete=no`     | Incomplete downloads |
| `is_open=y is_active=n` | Paused items    |
| `is_ghost=yes`       | Torrents that have no data (were never started or lost their data; _since v0.3.3_) |
| `alias=obt`          | Torrents tracked by `openbittorrent.com` (see UserConfiguration on how to add aliases for trackers) |
| `'path=!'`           | Has a non-empty `path` |
| `ratio=+1 realpath=\!/mnt/*` | 1:1 seeds not on a mounted path (i.e. likely on localhost) |
| `completed=+2w`      | Completed more than 2 weeks ago (_since v0.3.4_) |
| `tagged=`            | Not tagged at all (_since v0.3.5_) |
| `tagged=\!`          | Has at least one tag (_since v0.3.5_) |
| `tagged=foo,bar`     | Tagged with "foo" or "bar" (_since v0.3.5_) — tags are white-space separated lists of names in the field "custom\_tags" |
| `tagged==highlander` | _Only_ tagged with "highlander" and nothing else (_since v0.3.6_) |
| `kind=flac,mp3`      | Music downloads (_since v0.3.6_) |
| `files=sample/*`     | Items with a top-level `sample` folder (_since v0.3.6_) |
| `ratio=+2.5 OR seedtime=+1w` | Items seeded to 5:2 **or** for more than a week (_since v0.3.6_) |
| `alias=foo [ ratio=+2.5 OR seedtime=+7d ]` | The same as above, but for one tracker only (_since v0.3.7_) |
| `traits=avi traits=tv,movies` | TV or movies in AVI containers (_since v0.3.7_) |

Note that the `!` character has to be escaped in shell commands. For a current full list of all the field names and their meaning, see the output of [rtcontrol --help-fields](CliUsage#rtcontrol.md).


# Integrating rtcontrol into the curses UI #
Anyone who ever dreamt about a _[search box](http://www.youtube.com/watch?v=y8gHEfA1w3Y)_ in their rtorrent UI, dream no more...

![https://pyroscope.googlecode.com/svn/trunk/pyrocore/docs/videos/rtcontrol-curses.gif](https://pyroscope.googlecode.com/svn/trunk/pyrocore/docs/videos/rtcontrol-curses.gif)

Just add this to your `.rtorrent.rc` (note that you already have these if you followed the [configuration guide](UserConfiguration.md)):
```
# VIEW: Use rtcontrol filter (^X s=KEYWORD, ^X t=TRACKER, ^X f="FILTER")
system.method.insert = s,simple,"execute_nothrow=rtcontrol,--detach,-qV,\"$cat=*,$argument.0=,*\""
system.method.insert = t,simple,"execute_nothrow=rtcontrol,--detach,-qV,\"$cat=\\\"alias=\\\",$argument.0=\""
system.method.insert = f,simple,"execute_nothrow=rtcontrol,--detach,-qV,$argument.0="
```
You can of course add as many commands as you like, and include sorting options and whatever else `rtcontrol` offers.

The 'trick' here is the `-V` (`--view-only`) option, which shows the selection result in a rTorrent view instead of on the console. You can add this to any query you execute on the command line, and then interactively work with the result. The above commands are just shortcuts for common use-case directly callable from the curses UI.


# Reports #
## Using bash aliases for common reports ##
You might want to add the following alias definitions to your `~/.bashrc`:
```
alias rthot="watch -n10 'rtcontrol -rs up,down,name xfer=+0 2>&1'"
alias rtmsg="rtcontrol -s alias,message,name 'message=?*' message=\!*Tried?all?trackers*"
alias rtmsgstats="rtcontrol -q -s alias,message -o alias,message 'message=?*' message=\!*Tried?all?trackers* | uniq -c"
alias rt2days="rtcontrol -scompleted -ocompleted,is_open,up.sz,ratio,alias,name completed=-2d"
```

`rthot` shows active torrents every 10 seconds (until you hit CTRL-C), `rtmsg` lists all torrents that have a non-trivial tracker message, `rtmsgstats` prints a count of how many messages there are per unique combination of tracker and message text, and finally `rt2days` gives the completion history of the last 48 hours.

## Defining and using custom output formats ##

Before describing the possible options for output formatting in more details below, here's a short overview of the possible methods, each with an example:
  * `size.sz,name` — simple field lists, possibly with format specifiers; the fields are separated by a TAB character.
  * `%(size.sz)s %(name)s` — string interpolation, i.e. like the above lists, but interspersed with literal text.
  * `{{d.size|sz}} {{d.name}}` — Tempita templates, see OutputTemplates for more details.
  * `file:template.tmpl` — File URLs that point to a template file, which is especially useful for more complicated templates. The filenames can be absolute (starting with a `/`), relative to your home (starting with a `~`), or relative to `templates` in the configuration directory (anything else).
  * `«formatname»` — A name of a custom format from the `[FORMATS]` configuration section, see `~/.pyroscope/config.ini.default` for the predefined ones (including the special `default` format).

Starting with version 0.3.5, you can define custom output formats and print column headers, the `rt2days` example from the previous section becomes this:
```
alias rt2days="rtcontrol --column-headers -scompleted -ocompletion completed=-2d"
```

You need to define the custom output format used there, so also add this to your `~/.pyroscope/config.ini`:
```
[FORMATS]
# Custom output formats
completion = $(completed.raw.delta)13.13s $(leechtime)9.9s $(is_open)4.4s $(up.sz)10s/s $(ratio.pc)5d$(pc)s $(alias)-8s $(kind_50)-4.4s  $(name)s
```
See [String Formatting Operations](http://docs.python.org/release/2.5.2/lib/typesseq-strings.html) for a description how the formatting options work, and notice that `$` is used instead of `%` here, because `%` has a special meaning in INI files. For the same reason, a single `%` in the final output becomes `$(pc)s` in the configuration (`pc` is a system field that is simply a percent sign).

You can also append one or more format specifiers to a field name, separated by a '`.`'. These take the current value and transform it — in the above example `.raw.delta` means "take an unformatted time value and then convert it into a time delta relative to just now". The option `--help-fields` lists the available format specifiers.

Then, calling `rt2days -q` will print something like this;
```
    COMPLETED LEECHTIME IS_O         UP/s RATIO% ALIAS    KIND  NAME
   1d 21h ago   10m  2s  OPN    0 bytes/s   100% SeedBox  rar   lab-rats
```

And with version 0.3.6 installed, you can create a full listing of all the files you have loaded into rTorrent using the built-in format "`files`":
```
$ rtcontrol \* -ofiles | less
STP    1970-01-01 01:00:00   25.6 MiB Execute My Liberty - The Cursed Way -- Jamendo - OGG Vorbis q7 - 2010.07.29 [www.jamendo.com] {Jamendo}
       2010-08-21 01:25:27    2.0 MiB | 01 - Midnight (Intro).ogg
       ...
       2010-08-21 01:25:27   48.7 KiB | [cover] Execute My Liberty - The Cursed Way.jpg
                                      = 9 file(s) [ogg txt]
...
```

And finally, from version 0.4.1 onwards, you can use a full templating language instead of the simple field lists or string interpolation described above, more on that on the OutputTemplates page.


# Statistics #

## Printing some statistics to the terminal ##
Create a list of all your trackers and how many torrents are loaded for each:
```
rtcontrol -q -o alias -s alias \* | uniq -c
```
You can easily modify this by using conditions other than `*`, e.g. show the count of fully seeded downloads using `ratio=+1`. Or try the same command with `traits` instead of `alias` (version 0.3.7 only).

The total amount of data you have loaded in GB:
```
rtcontrol -qosize \* | awk '{ SUM += $1} END { print SUM/1024/1024/1024 }'
```

The amount uploaded per tracker:
```
rtcontrol -qo alias,uploaded // \
    | awk '{arr[$1]+=$2} END {for (i in arr) {printf "%20s %7.1f GiB\n",i,arr[i]/1024^3}}' \
    | sort -bnk21
```

Starting with version 0.4.1, you can also request a statistical summary of your numerical output columns, like this:
```
$ rtcontrol -qo size.sz,uploaded.sz,ratio.pc --summary "a*"
      SIZE	  UPLOADED	RATIO
  14.5 GiB	   9.3 GiB	2592.0 [SUM of 32 item(s)]
 462.4 MiB	 298.9 MiB	81.0 [AVG of 32 item(s)]
```


## Normalized histogram of ratio distribution ##
The following will create a normalized histogram of ratio distribution of your loaded torrents. Each bar indicates the percentage of items in a ratio class (i.e. the first bar shows ratios up to 1).
```
rtcontrol alias=* -qo ratio -s ratio >/tmp/data \
 && octave -q --persist --eval \
           "load /tmp/data; hist(data, $(tail -n1 /tmp/data), 100); print -dpng /tmp/ratio.png"
```

![https://pyroscope.googlecode.com/svn/trunk/pyrocore/docs/examples/ratio_histo.png](https://pyroscope.googlecode.com/svn/trunk/pyrocore/docs/examples/ratio_histo.png)

You need to have [Octave](http://www.gnu.org/software/octave/) installed, on Debian/Ubuntu all you need is `sudo aptitude install octave3.0`.


# Performing management tasks #
## Fixing items with an empty "Base path" ##
Sometimes rTorrent loses track of where it stores the data for an item, leading to an empty `Base path` in the `Info` panel. You can try to fix this by selectively rehashing those, with these commands:
```
rtcontrol path= is_complete=y -V
rtcontrol path= is_complete=y --hash -i
```
The first command selects the broken items into a rTorrent view, so that you can watch the progress of hashing and the results afterwards. If all of them are finished, you can then start those that were successfully restored like so:
```
rtcontrol path=\! done=100 --from-view rtcontrol --start
```
(note that the `--from-view` option needs version 0.3.7)

## Deleting download items and their data ##

Using the option `--cull` of version 0.3.10, an item can be deleted including its data. You can do this either manually, or automatically as a part of ratio management (see the section further below on that topic).

Called from the shell, you will first be presented with the number of items found and then asked for each of them whether you want to delete it (interactive mode is on by default). Therefor, for automatic uses in cron, you should also specify the `--yes` option.

If you define the following command shortcut, you can also delete the current item directly from ncurses (needs version 0.4.1 to work):
```
system.method.insert = cull,simple,"execute_nothrow=rtcontrol,-q,--detach,--cull,--yes,\"$cat=hash=,$d.get_hash=\""
```
Just select the item you want to annihilate and enter `cull=` into the command prompt (`Ctrl-X`).

## Pruning partial downloads ##

Starting with version 0.3.10, the `--purge` option (a/k/a `--delete-partial`) allows you to not only delete the selected items from the client, but at the same time delete any incomplete files contained in them (i.e. files that are part of an incomplete chunk).

For technical reasons, rTorrent has to create files that you have deselected from download to save data of chunks that border selected files, and this option can be a great time saver, especially on large torrents containing hundreds of files.
So, unless you have filtered out incomplete items by the appropriate conditions, using `--purge` instead of `--delete` is always the better option.

As with `--cull`, a shortcut command to call this from the curses UI is useful:
```
system.method.insert = purge,simple,"execute_nothrow=rtcontrol,-q,--detach,--purge,--yes,\"$cat=hash=,$d.get_hash=\""
```


# Performing periodic tasks (cron jobs) #

## Simple Queue Management ##

This is a queue management one-liner (well, logically one line). Before you run it automatically, add a trailing "-n" to test it out, e.g. play with the queue size parameter and check out what would be started. Then put it into a script, crontab that and run it every (few) minute(s).
```
export rt_max_start=6; rtcontrol -q --start --yes hash=$(echo $( \
    rtcontrol -qrs is_active -o is_open,hash is_complete=no is_ignored=no \
    | head -n $rt_max_start | grep ^CLS | cut -f2 ) | tr " " ,)
```
It works by listing all incomplete downloads that heed commands and sorting the already active ones to the top. Then it looks at the first `rt_max_start` entries and starts any closed ones.

Note that this means you can exempt items from queue management easily by using the `I` key in the curses interface. See QueueManager for a much better solution.


## Move on Completion ##

The following moves completed downloads _still physically residing_ in a `work` directory (change the `realpath` filter when you named your download directory differently), to another directory (note that you can restrict this further, e.g. to a specific tracker by using "alias=NAME"). You don't need any multiple watch folders or other prerequisites for this.
```
rtcontrol --from-view complete 'realpath=*/work/*' -qo '~/bin/rtmv "$(path)s" ~/rtorrent/done --cron' | bash
```
Test it first **without the "`| bash`" part** at the end, to make sure it'll in fact do what you intended.

Another advantage is that in case you ever wanted to switch clients, or exchange the drive you host the data on, you can do so easily since all the active downloads still reside at one place in your download directory (in form of a bunch of symlinks) — even if their data is scattered all over the place in reality.

You can also extend it to create more organized completion structures, e.g. creating a directory tree organized by month and item type, as follows:
```
RT_SOCKET=/home/bt/rtorrent/.scgi_local

# Move completed torrents to "done", organized by month and item type (e.g. "2010-09/tv/avi")
*/15    * * * *         test -S $RT_SOCKET && ~/bin/rtcontrol --from-view complete 'realpath=*/work/*' -qo '~/bin/rtmv "$(path)s" ~/rtorrent/done//$(now.iso).7s/$(traits)s --cron' | bash
```
The above is a fully working crontab example, you just have to adapt the paths to your system. If you want to create other organizational hierarchies, like "by tracker", just replace the `$(now.iso).7s/$(traits)s` part by `$(alias)s`. And if you don't want the file type in there (i.e. just "tv"), use `$(traits.pathdir)s` to have it removed.

To get themed trackers specially treated, you can add hints to the `[TRAITS_BY_ALIAS]` section of the config (see `config.ini.default` for examples).

Afterwards, you can always move and rename stuff at will _and still continue seeding_, by using the `rtmv` tool in version 0.3.7 ­— this will rename the data file or directory at its current location and automatically fix the symlink in the download directory to point at the new path. Example:
```
cd ~/rtorrent/done/2010-09/tv/avi
rtmv foo.avi bar.avi
```


## Ratio Management ##

While rTorrent has a built-in form of ratio management since a few versions, it's hard to use after-the-fact and also hard to understand — you need to have different watch directories and complex settings in your `.rtorrent.rc`.

A basic form of ratio management using `rtcontrol` looks like this:
```
rtcontrol is_complete=yes is_open=yes ratio=+1.1 alias=sometracker,othertracker --stop
```
You will always want to have the `is_complete=yes is_open=yes ratio=+1.1` part, which excludes all torrents that are still downloading, closed or not having the necessary ratio. Another basic filter is `is_ignored=no`, which excludes items that have their _ignore commands_ flag set (via the `I` key) from ratio management.

To that you can add anything you think fits your needs, and also use several commands with different minimum ratios for different trackers by selecting them using `alias` or `tracker`, like in the example above. Assuming you have your original seeds in a directory named `seed` and don't want to ratio-limit them, one thing you might add is `'datapath=!*/seed/*'` to prevent them from being stopped. Only your imagination (and the available fields) are the limit here.

If you then put these commands into a script that runs every few minutes via `cron`, you have a very flexible form of ratio management that can be changed on a whim.

To complete your command line, you add the action you want to take on the torrents found, in the above example `--stop`; `--delete` is another possibility, which removes the item from the client, but leaves the data intact. Starting with version 0.3.10, you can also delete the downloaded data by using the `--cull` option.


## Bandwidth Management ##

Say you want to have torrents that are already seeded back take a back-seat when other torrents with a ratio less than 100% are active — but when they're not, all torrents should take full advantage of the available bandwidth. The last part is not possible with the built-in throttle groups, but here's a fix that works by setting the maximum rate on the `seed` throttle dynamically.

Put this into your `.rtorrent.rc`:
```
throttle_up=seed,900
```

Then save the [dynamic seed throttle](https://pyroscope.googlecode.com/svn/trunk/pyrocore/docs/examples/rt_cron_throttle_seed) script into `~/bin/rt_cron_throttle_seed`.

Finally, extend your crontab with these lines (`crontab -e`):
```
RT_SOCKET=/home/bt/rtorrent/.scgi_local
BW_SEED_MAX=900
BW_SEED_SLOW=200

# Throttle torrents that are seeded 1:1 when there are other active ones
*	* * * * 	test -S $RT_SOCKET && ~/bin/rt_cron_throttle_seed seed $BW_SEED_MAX $BW_SEED_SLOW --cron

# Put torrents seeded above 1:1 into the seed throttle
*/10	* * * * 	test -S $RT_SOCKET && rtcontrol ratio=+1.05 is_complete=1 is_ignored=0 throttle=none -q -T seed --yes --cron
```

The `900` and `200` in the above examples are the bandwidth limits in KiB/s, you need to adapt them to your connection of course, and all paths need to be changed to fit your system. Each time the throttle rate is changed, a line like the following will be appended to the file `~/.pyroscope/log/cron.log`:
```
2010-08-30 14:16:01 INFO     THROTTLE 'seed' up=200.0 KiB/s [2 prioritized] [__main__.SeedThrottle]
```

## Automatic stop of torrents having problems ##

This takes away a lot of manual monitoring work you had to do previously:
```
RT_SOCKET=/home/bt/rtorrent/.scgi_local

# Stops any torrent that isn't known by the tracker anymore,
# or has other authorization problems, or lost its data
*	* * * * 	test -S $RT_SOCKET && ~/bin/rtcontrol --from-view started prio=-3 'message=*not?registered*,*unregistered*,*not?authorized*' OR is_complete=yes is_ghost=yes --stop --cron
```
Note that this means you can simply stop torrents by removing their data, it won't take more than a minute. The `prio=-3` enables you to keep items running in case of errors, by setting their priority to high, e.g. when only some trackers in a longer list return errors.