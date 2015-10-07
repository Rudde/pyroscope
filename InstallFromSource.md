

> ➽ _If you want to **update** your already installed software, go to the MigrationGuide instead!_


# Installing from source #
If you have experience with the shell prompt and possibly a bit of Python you might want to install the development version to gain early access to new features. Since that version is constantly used in cron jobs, chances that it is unstable at any point in time are slim. Please **monitor the [SVN log](http://code.google.com/p/pyroscope/source/list) and the [changelog](http://code.google.com/p/pyroscope/source/browse/trunk/debian/changelog)** if you run from source.

For a working installation, you have to meet these requirements first:
  * Python 2.6 or a higher 2.x version (2.7 is recommended).
  * A proper build environment and a subversion + git client. On Debian and Ubuntu, you'll need the following packages installed (if there are packages missing from that list, please leave a comment):
```
aptitude install python python-dev build-essential subversion git
```
  * For `rtcontrol` and `rtxmlrpc`, an existing rTorrent installation, _with the xmlrpc option compiled in_ and the `scgi_local` or `scgi_port` command added to your `~/.rtorrent.rc`.
  * Using rTorrent **0.9.4** or **0.9.2** is recommended — PyroScope _should_ work together with older versions though, up to a point.

The installation of `pyrocore` is done from source, see [GitHub](https://github.com/pyroscope/pyrocore#installation) for more details.
Do **NOT** do this as `root` or using `sudo`.

**If you want to switch over from an old installation based on subversion source (from Google code), then move that old directory away, before installation!** Like this: `( cd ~/lib && mv pyroscope pyroscope-$(date +'%Y-%m-%d').bak )`

```
# Run this in your NORMAL user account!
mkdir -p ~/bin ~/lib
git clone "https://github.com/pyroscope/pyrocore.git" ~/lib/pyroscope

# Pass "/usr/bin/python2" or whatever to the script,
# if "/usr/bin/python" is not a suitable version
~/lib/pyroscope/update-to-head.sh

# Check success
pyroadmin --version
```

After that, the CommandLineTools are available in the `~/lib/pyroscope/bin` directory, and also added to your user's bin directory.
Make sure `~/bin` is on your `PATH`, and if not, close and then reopen your shell. Check again, and if it's still not in there, [fix your broken `.bashrc`](http://linux.about.com/od/linux101/l/blnewbie3_1_4.htm).

To finish installation, read the next section.


# Completing your setup #
After installation, you **must change your `rtorrent.rc`** using the instructions on the UserConfiguration page, else many features of `rtcontrol` won't work as expected. You should at least **create a configuration** as described there, using the `pyroadmin --create-config` command. If you encounter any problems during installation not covered by the documentation, subscribe to the [pyroscope-users](http://groups.google.com/group/pyroscope-users) mailing list to get help from the community, or join the inofficial <a href='irc://irc.freenode.net/rtorrent'><code>##rtorrent</code></a> channel on `irc.freenode.net`.