"""The shapes of an app's cards and of the rows its page and credential routes answer, in the keys the reply models in
`apps.py` read (`SystemCard`, `AppCredential`, `AppPage` and the rows inside them). They are plain dicts at run time;
the models validate them where the routes answer."""

from typing import Literal, NotRequired, TypedDict

from ops_service_kit.http import Json, JsonList, JsonValue

from .app_states import AppGroup
from .connections.service import AccountView
from .plugins.host import IdentityRow, SignInValueRow

# An app credential's status, from the last Test with my account (connections.service check_credential).
CredentialStatus = Literal["working", "not_tested", "failing"]


class SettingOfferChoice(TypedDict):
    """One value a setting takes, as the Connect window draws it."""

    value: bool | int | float | str
    label: str
    hint: str
    testAccount: bool


class SettingOfferOther(TypedDict):
    """A host typed in place of a choice."""

    label: str
    hint: str
    placeholder: str
    value: str
    hosts: list[str]
    testAccountHosts: list[str]


class SettingOffer(TypedDict, total=False):
    """A setting's choices and typed host; a key is left out for a setting that has none."""

    choices: list[SettingOfferChoice]
    other: SettingOfferOther


class CardSetting(SettingOffer):
    """One setting a team types on a plugin card (the keys of `PluginSetting`)."""

    name: str
    label: str
    default: str | None
    secret: bool
    perAccount: bool
    locked: bool
    credential: bool
    asked: Literal["config", "connect", "settings"] | None


class PermissionRow(TypedDict):
    id: str
    label: str
    required: bool


class CardPlugin(TypedDict):
    """A plugin card's details (the keys of `SystemPlugin`)."""

    teamOn: bool
    platformApp: bool
    kinds: list[str]
    signIn: list[str]
    scopes: list[PermissionRow]
    settings: list[CardSetting]
    values: dict[str, JsonValue]
    fixed: list[str]
    tools: list[str]
    teamVersion: str | None
    updateAvailable: bool


class CardCredentialRow(TypedDict):
    """Whose OAuth app a card's account signs in with (the keys of `CardCredential`)."""

    id: str | None
    name: str
    type: Literal["ops_ai", "own"]


class CardDraft(TypedDict):
    """One app card before its state is known, in the keys `SystemCard` takes: the first group is on every kind of
    card, the second is what each kind adds."""

    id: str
    kind: Literal["plugin", "connection", "module", "builtin"]
    name: str
    toolsCount: int
    moduleIds: list[str]
    mayManage: bool
    logo: NotRequired[str | None]
    category: NotRequired[str | None]
    description: NotRequired[str | None]
    docsUrl: NotRequired[str | None]
    toolsAdded: NotRequired[int]
    accountsCount: NotRequired[int]
    authKind: NotRequired[str | None]
    kindLabel: NotRequired[str | None]
    connectionId: NotRequired[str | None]
    pluginId: NotRequired[str]
    sandboxId: NotRequired[str | None]
    status: NotRequired[str | None]
    state: NotRequired[str | None]
    managedClient: NotRequired[bool]
    plugin: NotRequired[CardPlugin]
    href: NotRequired[str]


class AppCard(CardDraft):
    """A card with the caller's state of it (`Apps._app_states`), as every answer carries it."""

    appState: str
    appStateReason: str | None
    appGroup: AppGroup
    credential: CardCredentialRow | None
    signIn: str | None
    ownSignIn: Literal["connected", "expired", "none"] | None


class ConfigFieldRow(SettingOffer):
    """One setting an auth config holds (the keys of `CredentialField`, and with `value`, `mode` and `shown` of
    `ConfigField`). A custom app's client field names only what its kind says of it."""

    name: str
    label: str
    required: NotRequired[bool]
    default: NotRequired[str | None]
    help: NotRequired[str]
    pem: NotRequired[bool]
    value: NotRequired[str | None]
    mode: NotRequired[str | None]
    shown: NotRequired[str | None]


class CredentialAccountRow(TypedDict):
    """An account signing in with an app credential (the keys of `CredentialAccount`)."""

    id: str
    name: str
    sandbox: bool
    state: str
    status: str
    stateReason: str | None
    signIn: str
    connectedAt: str | None


class CredentialRow(TypedDict):
    """One app credential's row (the keys of `AppCredential`)."""

    teamId: str
    secretEnds: str | None
    holdsSecret: bool
    id: str
    name: str
    app: str
    appName: str
    type: Literal["ops_ai", "own"]
    clientId: str | None
    permissions: list[PermissionRow]
    accounts: int
    status: CredentialStatus
    created: str | None
    createdBy: str | None


class CredentialDetailRow(CredentialRow):
    """An app credential's page (the keys of `AppCredentialDetail`)."""

    accountsList: list[CredentialAccountRow]
    redirectUri: str | None
    updated: str | None
    settings: Json
    modes: dict[str, str]
    fields: list[ConfigFieldRow]


class CredentialChangeRow(CredentialDetailRow):
    """What an edit of an app credential answers (the keys of `AppCredentialChange`)."""

    signInAgain: int


class NamesRow(TypedDict):
    """The accounts an app delete or a kind change names (the keys of `AppDeleted`, `AppKindChanged`)."""

    accounts: list[str]


class MovedRow(TypedDict):
    """How many accounts a credential delete moved (the keys of `CredentialDeleted`)."""

    moved: int


class ToolUserRow(TypedDict):
    id: str
    name: str


class ToolUsedByRow(TypedDict):
    agents: list[ToolUserRow]
    workflows: list[ToolUserRow]


class ToolRow(TypedDict):
    """One tool of an app as the page and the add route answer it (the keys of `AppTool`)."""

    name: str
    title: str
    access: str
    added: bool
    askedAtSignIn: bool
    usedBy: NotRequired[ToolUsedByRow]


class CardToolRow(ToolRow):
    """A tool as the card holds it: with whether a call waits for approval by its own flag, the team's setting and
    the module that holds it."""

    waits: bool
    setting: str | None
    settingRole: str | None
    moduleId: str


class SkillRow(TypedDict):
    kind: str
    id: str
    title: str


class AccountChoiceRow(TypedDict):
    """One account a call may name (the keys of `AccountChoice`)."""

    id: str
    name: str
    identity: list[IdentityRow]
    default: bool
    sandbox: bool
    own: bool
    app_id: str
    missing_objects: list[str]


class AccountOwnerRow(TypedDict):
    kind: Literal["team", "each", "person"]
    name: str


class AccountRowOnPage(TypedDict):
    """One row of the app page's Accounts list (the keys of `AppAccount`); the last three are added once the row's
    identity is known."""

    rowId: str
    kind: Literal["team", "person"]
    id: str
    name: str
    revision: int
    default: bool
    sandbox: bool
    state: str
    status: str
    statusDetail: str | None
    stateReason: str | None
    owner: AccountOwnerRow
    signIn: str
    peopleSignedIn: int
    configId: str | None
    configName: str | None
    actions: list[str]
    mine: bool
    account: str | None
    myDefault: bool | None
    test: JsonValue
    health: Json | None
    signInValues: list[SignInValueRow]
    identity: NotRequired[list[IdentityRow]]
    samePlaceAs: NotRequired[str | None]
    pointsAt: NotRequired[str | None]


class ConfigPermissionRow(TypedDict):
    id: str
    label: str
    askedAtSignIn: bool


class AuthConfigBase(TypedDict):
    """An auth config before its account count and permissions are known (the keys of `AuthConfig`)."""

    id: str
    name: str
    type: Literal["ops_ai", "own", "account"]
    canEdit: bool
    canDelete: bool
    clientId: NotRequired[str | None]
    secretEnds: NotRequired[str | None]
    fields: NotRequired[list[ConfigFieldRow]]


class AuthConfigRow(AuthConfigBase):
    default: bool
    accountCount: int
    signInPlace: str | None
    permissions: list[ConfigPermissionRow]


class AppMeRow(TypedDict):
    connected: bool
    account: str | None
    signIns: int


class AppPageRow(TypedDict):
    """One app's page (the keys of `AppPage`)."""

    card: AppCard
    connection: AccountView | None
    me: AppMeRow
    peopleCount: int
    accounts: list[AccountRowOnPage]
    authConfigs: list[AuthConfigRow]
    tools: list[ToolRow]
    skills: list[SkillRow]
    usage: JsonList
