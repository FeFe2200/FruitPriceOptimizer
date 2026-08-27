import asyncio
import getpass
import sys

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Site
from app.security import CredentialCipher


async def update_credentials(domain: str) -> None:
    username = input("새 사이트 아이디: ")
    password = getpass.getpass("새 사이트 비밀번호: ")
    if not username or not password:
        raise SystemExit("아이디와 비밀번호는 비워둘 수 없습니다")

    async with SessionLocal() as session:
        sites = list((await session.scalars(select(Site).where(Site.domain == domain))).all())
        if not sites:
            raise SystemExit(f"등록된 도메인이 없습니다: {domain}")
        if len(sites) > 1:
            print("같은 도메인이 여러 개입니다. 사이트 ID를 지정해 다시 실행하세요:")
            for site in sites:
                print(f"  id={site.id} name={site.name}")
            raise SystemExit(2)

        cipher = CredentialCipher(settings.credential_key)
        sites[0].encrypted_username = cipher.encrypt(username)
        sites[0].encrypted_password = cipher.encrypt(password)
        await session.commit()
        print(f"수정 완료: id={sites[0].id}, domain={domain}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python scripts/update_site_credentials.py <domain>")
    asyncio.run(update_credentials(sys.argv[1].strip().lower()))
