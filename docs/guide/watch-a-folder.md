# Watch a folder

Status: current. Rows marked planned are designed and not built.

Files that live in an app, such as a SharePoint library of policies or supplier invoices, change all the time, and
copying them by hand means the copy goes stale. Watch a folder to have Files bring them in for you: one entry per file,
and a new version each time the file changes in the app.

## Try it

You need the app turned on for your team and signed in ([Set up an app](apps-setup.md)), and the Builder or Admin role.

1. Open **Data › Files** and choose the **Watched folders** tab.
2. Select **Watch a folder**.
3. Name it, for example "Supplier invoices", and pick the app. Select **Next**.
4. Pick the sites, libraries or folders to include. Each list searches by name. Add a rule under **Include** or
   **Exclude** to narrow it further; a rule starts with `/`, and Exclude wins. Select **Next**.
5. Read the review. It names the folders you picked. Files lists what it found after you select Check now. Select
   **Watch a folder**.
6. Nothing is copied yet. On the folder's row, open the menu and select **Check now**. The row shows **Checking…**, and a
   moment later it shows when the check ran and how many files it brought in.

The files are now in **All files**, marked as coming from a watched folder. Open one to see which folder it came from
and its place in the app.

## How it works

- **One entry per file.** A file keeps one entry in Files however often it changes. When a check finds a changed file it
  adds a new version to that entry and keeps the earlier one. A check takes the newest version of each file, so a file
  changed three times between two checks arrives as one new version.
- **A renamed or moved file** stays the same entry.
- **A file removed from the folder** is marked as removed at the source. Files keeps it and its versions.
- **Each check reads from the app on your team's connection.** If the app refuses the sign-in or cannot be reached, the
  check stops, nothing is lost, and the page says why and what to do. Reconnecting the app is on its page under
  **Data › Apps**.
- **Everyone on the team can read the files that arrive,** whatever access they have in the app. Files records who may
  see each file in the app but does not apply it yet. Pick folders the whole team may see.

## Failed files

A check that cannot bring one file in names it in the **In Files** column of the folder's row, with its size and the
reason. The other files in the check still arrive.

| Reason | What it means | What to do |
|---|---|---|
| Larger than 25 MB | A watched folder takes files up to 25 MB | Split the file or make it smaller in the app, or upload it to Files directly with **Upload** on **All files**. A file that is made smaller is tried again on the next check |
| Could not be fetched | The app did not hand over that one file | The next checks try it again, up to three times. If it still fails, change the file in the app or upload it directly |

A file larger than the limit is listed once with its size. It is listed again only if the file changes.

A check that stopped part way says **Partial** and why, for example that the app slowed the check down or that the
folder is long. The next check carries on from there.

## Check now, change and stop

| Action | What it does |
|---|---|
| Check now | Runs a check at once. A folder that is already being checked says so instead of starting a second one |
| Change folders | Changes the name or the folders picked. The new folders are read whole on the next check. The app stays the same: to use another connection, add a new watched folder |
| Stop watching | Files stops checking this folder. The files already brought in stay in Files, with their versions, and keep following their retention rules like any other file. Files that change in the app after that are not brought in |

Stopping is in the folder's row menu. Files never deletes a brought-in file because you stopped watching; delete a file
from **All files** if you want it gone.

## Who may do what

| Who | Can |
|---|---|
| Admin and Builder | Watch a folder, change its folders, check it now and stop watching it. Each is recorded in the audit log with the folders named |
| Anyone who can see Files | Read the list of watched folders, their last check and the files that arrived. They see no buttons for the actions above |

## Limits

- A check runs when someone presses **Check now**. Checks on a schedule are planned.
- SharePoint and OneDrive are the apps a folder can be watched from today. Others are planned.
- A file over 25 MB is not brought in.
- A workflow that starts when a watched folder brings in a file is planned.

## Next

- [Tools and apps](apps.md): what an app is and how its sign-in works
- [Set up an app](apps-setup.md): turn on and sign in SharePoint
- [Knowledge](knowledge.md): read the same folders into a knowledge base instead
- [Teams and access](teams-and-access.md): what each role may do
