# WireVault FabOS 0.15.1 Beta — Products Compatibility Fix

## Fixed
Opening Products on older Windows/Tkinter installations could raise:

`value for "-command" missing`

The Catalog's new non-sortable `Print File` heading was explicitly passing `command=None`
to `ttk.Treeview.heading()`. Some older Tk builds interpret that as a missing Tcl argument.

FabOS now:
- supplies a heading callback only for sortable columns
- omits the `command` option completely for the `Print File` column
- retains sorting on Product, Category, Price, Print Time and License
- retains Ready to Print / Needs Attention behavior

A regression test now prevents `command=None` from returning to Catalog headings.
