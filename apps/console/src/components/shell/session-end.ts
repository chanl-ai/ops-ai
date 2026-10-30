// Tells the shell a sign-out was the person's own choice (the person menu's Sign out), so it goes to the sign-in page;
// any other sign-out after the person was in means the session ended, and the shell keeps the page under a sign-in
// dialog instead (c-552).
let chosen = false;

export function noteChosenSignOut() {
  chosen = true;
}

export function signOutWasChosen(): boolean {
  return chosen;
}

/** Signed in again: the next sign-out is judged afresh. */
export function resetChosenSignOut() {
  chosen = false;
}
