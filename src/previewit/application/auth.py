"""Authentication use cases: password and external (OIDC/SAML) logins."""

from __future__ import annotations

from collections.abc import Callable

from previewit.application.ports import (
    DuplicateEmail,
    DuplicateIdentity,
    PasswordHasher,
    UserRepository,
)
from previewit.domain.identity import (
    CreateUser,
    Email,
    ExternalClaims,
    InvalidEmail,
    LinkIdentity,
    SignIn,
    User,
    UserId,
    check_password,
    decide_external_login,
)


class EmailTaken(Exception):
    pass


class WeakPassword(Exception):
    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.problem = problem


class InvalidCredentials(Exception):
    pass


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        new_id: Callable[[], str],
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._new_id = new_id

    def get_user(self, user_id: UserId) -> User | None:
        return self._users.get(user_id)

    def register_with_password(self, email: str, password: str, display_name: str) -> User:
        address = Email(email)  # raises InvalidEmail
        problem = check_password(password)
        if problem is not None:
            raise WeakPassword(problem)
        user = User(
            id=UserId(self._new_id()),
            display_name=display_name.strip() or address.value.split("@")[0],
            email=address,
            email_verified=False,
            identities=frozenset(),
            has_password=True,
        )
        try:
            self._users.add_user(user, self._hasher.hash(password))
        except DuplicateEmail:
            raise EmailTaken from None
        return user

    def login_with_password(self, email: str, password: str) -> User:
        try:
            address = Email(email)
        except InvalidEmail:
            self._burn_time(password)
            raise InvalidCredentials from None
        user = self._users.find_by_email(address)
        stored = self._users.get_password_hash(user.id) if user else None
        if user is None or stored is None:
            self._burn_time(password)
            raise InvalidCredentials
        if not self._hasher.verify(stored, password):
            raise InvalidCredentials
        if self._hasher.needs_rehash(stored):
            self._users.set_password_hash(user.id, self._hasher.hash(password))
        return user

    def login_with_external(self, claims: ExternalClaims) -> User:
        for _ in range(2):  # the second pass handles a concurrent first login
            decision = decide_external_login(
                claims,
                by_identity=self._users.find_by_identity(claims.key),
                by_email=self._users.find_by_email(claims.email) if claims.email else None,
            )
            try:
                return self._apply(decision)
            except DuplicateIdentity:
                continue
        raise RuntimeError("external login failed twice on a duplicate identity")

    def _apply(self, decision: SignIn | LinkIdentity | CreateUser) -> User:
        match decision:
            case SignIn(user_id):
                user = self._users.get(user_id)
            case LinkIdentity(user_id, key, reset_password):
                self._users.add_identity(
                    user_id, key, clear_password=reset_password, verify_email=True
                )
                user = self._users.get(user_id)
            case CreateUser(key, email, verified, display_name):
                new = User(
                    id=UserId(self._new_id()),
                    display_name=(display_name or "").strip() or "Member",
                    email=email,
                    email_verified=verified,
                    identities=frozenset({key}),
                    has_password=False,
                )
                try:
                    self._users.add_user(new, None)
                except DuplicateEmail:
                    # raced with a password sign-up for the same address: retry the policy
                    raise DuplicateIdentity from None
                user = new
        assert user is not None
        return user

    def _burn_time(self, password: str) -> None:
        self._hasher.verify(self._hasher.dummy_hash(), password)
